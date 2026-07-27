'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const Y = 65
const ORIGIN_X = 0.69
const FRACTIONS = [0.241, 0.759]
const PITCHES = [80, 85, 89]
const YAWS = [-95, -90, -85]
const ESCAPE_STEPS = [0.05, 0.10, 0.20, 0.249]
const REPEATS = 3
const WALL_MIN_X = 1.0
const WALL_MAX_X = 2.0
const TARGET_X = 2.35
const WITNESS = new Vec3(5, 65, 0)

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

function onceWithTimeout (emitter, eventName, timeoutMs) {
  return new Promise(resolve => {
    let settled = false
    const timer = setTimeout(() => finish(null), timeoutMs)
    const handler = (...args) => finish(args)
    function finish (value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      emitter.removeListener(eventName, handler)
      resolve(value)
    }
    emitter.once(eventName, handler)
  })
}

async function command (bot, text, delay = 160) {
  bot.chat(text)
  await sleep(delay)
}

async function setupArena (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, '/fill -3 63 -3 7 70 3 minecraft:air')
  await command(bot, '/fill -3 64 -3 7 64 3 minecraft:stone')
  await command(bot, '/fill 1 65 -1 1 67 1 minecraft:obsidian')
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`)
  await command(bot, `/give ${USERNAME} minecraft:ender_pearl 256`, 500)
}

async function reset (bot, z) {
  const positionPromise = onceWithTimeout(bot._client, 'position', 3500)
  bot.chat(`/tp ${USERNAME} ${ORIGIN_X} ${Y} ${z} -90 89`)
  if (!await positionPromise) throw new Error('Reset position packet missing')
  await sleep(180)
  bot.entity.velocity = new Vec3(0, 0, 0)
}

async function ensurePearl (bot) {
  let pearl = bot.inventory.items().find(item => item.name === 'ender_pearl')
  if (!pearl) {
    await command(bot, `/give ${USERNAME} minecraft:ender_pearl 64`, 450)
    pearl = bot.inventory.items().find(item => item.name === 'ender_pearl')
  }
  if (!pearl) throw new Error('No ender pearl available')
  await bot.equip(pearl, 'hand')
  await sleep(100)
}

function degrees(value) {
  return value * Math.PI / 180
}

function packetPosition (packet) {
  return {
    x: Number.isFinite(packet.x) ? packet.x : null,
    y: Number.isFinite(packet.y) ? packet.y : null,
    z: Number.isFinite(packet.z) ? packet.z : null,
    teleportId: packet.teleportId ?? null,
    flags: packet.flags ?? null
  }
}

function overlapsWall (position) {
  const halfWidth = 0.30
  return position.x + halfWidth > WALL_MIN_X && position.x - halfWidth < WALL_MAX_X
}

async function sendEscape (bot, start, step, correctionEvents) {
  let x = start.x + step
  let packets = 0
  const started = process.hrtime.bigint()
  while (x < TARGET_X - 1e-9 && correctionEvents.length === 0) {
    bot._client.write('position', {
      x,
      y: start.y,
      z: start.z,
      flags: { onGround: false, hasHorizontalCollision: true }
    })
    bot.entity.position.set(x, start.y, start.z)
    packets++
    await sleep(50)
    x += step
  }
  if (correctionEvents.length === 0) {
    bot._client.write('position', {
      x: TARGET_X,
      y: start.y,
      z: start.z,
      flags: { onGround: false, hasHorizontalCollision: true }
    })
    bot.entity.position.set(TARGET_X, start.y, start.z)
    packets++
  }
  return {
    packets,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6
  }
}

async function authoritativeSnapshot (bot) {
  const packetPromise = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  await sleep(100)
  return {
    packet: args ? packetPosition(args[0]) : null,
    position: {
      x: bot.entity.position.x,
      y: bot.entity.position.y,
      z: bot.entity.position.z
    }
  }
}

async function openWitness (bot) {
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 80)
  let block = bot.blockAt(WITNESS)
  for (let attempt = 0; attempt < 15 && (!block || block.name !== 'barrel'); attempt++) {
    await sleep(80)
    block = bot.blockAt(WITNESS)
  }
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  }
  const opened = onceWithTimeout(bot, 'windowOpen', 1400)
  try {
    await bot.lookAt(WITNESS.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  if (!await opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function runTrial (bot, plan, id) {
  await reset(bot, plan.fraction)
  await ensurePearl(bot)
  await bot.look(degrees(plan.yaw), degrees(plan.pitch), true)
  await sleep(100)

  const pearlStarted = process.hrtime.bigint()
  const teleportPromise = onceWithTimeout(bot._client, 'position', 6500)
  bot.activateItem()
  const teleportArgs = await teleportPromise
  const pearlMs = Number(process.hrtime.bigint() - pearlStarted) / 1e6
  await sleep(100)

  if (!teleportArgs) {
    await sleep(1050)
    return {
      ...plan,
      id,
      pearlMs,
      pearlPacket: null,
      pearlPosition: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z },
      overlap: false,
      escapePackets: 0,
      escapeMs: 0,
      corrections: [],
      snapshot: { position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z } },
      witness: { opened: false, reason: 'no_pearl_teleport' },
      verified: false
    }
  }

  const pearlPacket = packetPosition(teleportArgs[0])
  const pearlPosition = {
    x: bot.entity.position.x,
    y: bot.entity.position.y,
    z: bot.entity.position.z
  }
  const overlap = overlapsWall(pearlPosition)
  const corrections = []
  const correctionStarted = process.hrtime.bigint()
  const correctionHandler = packet => corrections.push({
    elapsedMs: Number(process.hrtime.bigint() - correctionStarted) / 1e6,
    packet: packetPosition(packet)
  })
  bot._client.on('position', correctionHandler)

  let escape = { packets: 0, elapsedMs: 0 }
  if (overlap) {
    escape = await sendEscape(bot, pearlPosition, plan.escapeStep, corrections)
    await sleep(500)
  }
  bot._client.removeListener('position', correctionHandler)

  const snapshot = await authoritativeSnapshot(bot)
  const beyond = snapshot.position.x >= TARGET_X - 0.05
  const witness = beyond && corrections.length === 0
    ? await openWitness(bot)
    : { opened: false, reason: overlap ? (corrections.length ? 'server_setback' : 'not_beyond') : 'no_overlap' }
  await sleep(1050)

  return {
    ...plan,
    id,
    pearlMs,
    pearlPacket,
    pearlPosition,
    overlap,
    escapePackets: escape.packets,
    escapeMs: escape.elapsedMs,
    corrections,
    snapshot,
    beyond,
    witness,
    verified: overlap && corrections.length === 0 && beyond && witness.opened
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'pearl-overlap-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      repeats: REPEATS,
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['id,fraction,pitch,yaw,escape_step,repeat,pearl_ms,pearl_x,pearl_y,pearl_z,overlap,escape_packets,escape_ms,corrections,first_correction_ms,post_x,post_y,post_z,beyond,witness,verified']
  for (const result of results) {
    const first = result.corrections[0]
    rows.push([
      result.id,
      result.fraction,
      result.pitch,
      result.yaw,
      result.escapeStep,
      result.repeat,
      result.pearlMs.toFixed(3),
      result.pearlPosition.x.toFixed(6),
      result.pearlPosition.y.toFixed(6),
      result.pearlPosition.z.toFixed(6),
      result.overlap,
      result.escapePackets,
      result.escapeMs.toFixed(3),
      result.corrections.length,
      first ? first.elapsedMs.toFixed(3) : '',
      result.snapshot.position.x.toFixed(6),
      result.snapshot.position.y.toFixed(6),
      result.snapshot.position.z.toFixed(6),
      result.beyond,
      result.witness.opened,
      result.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'pearl-overlap-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab pearl overlap matrix complete')
  } catch (_) {}
  await sleep(250)
  process.exit(code)
}

async function main () {
  const bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username: USERNAME,
    auth: 'offline',
    version: '1.21.11',
    physicsEnabled: false,
    hideErrors: false
  })
  bot.on('kicked', reason => console.error('[PearlOverlap kicked]', reason))
  bot.on('error', error => console.error('[PearlOverlap error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Pearl overlap bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setupArena(bot)

    const plans = []
    for (const fraction of FRACTIONS) {
      for (const pitch of PITCHES) {
        for (const yaw of YAWS) {
          for (const escapeStep of ESCAPE_STEPS) {
            for (let repeat = 1; repeat <= REPEATS; repeat++) {
              plans.push({ fraction, pitch, yaw, escapeStep, repeat })
            }
          }
        }
      }
    }

    const results = []
    for (let id = 0; id < plans.length; id++) {
      const result = await runTrial(bot, plans[id], id)
      results.push(result)
      writeReport(results, bot)
      console.log(`[PearlOverlap] ${id + 1}/${plans.length}` +
        ` frac=${result.fraction} pitch=${result.pitch} yaw=${result.yaw}` +
        ` step=${result.escapeStep} overlap=${result.overlap}` +
        ` corrections=${result.corrections.length}` +
        ` postX=${result.snapshot.position.x.toFixed(3)}` +
        ` verified=${result.verified}`)
    }

    const overlapCount = results.filter(result => result.overlap).length
    const verified = results.filter(result => result.verified).length
    console.log(`[PearlOverlap] completed=${results.length} overlaps=${overlapCount} verified=${verified}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[PearlOverlap fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
