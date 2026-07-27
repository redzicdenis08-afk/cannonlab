'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const VERTICAL_ORIGIN = new Vec3(0.69, 65, 0.5)
const VERTICAL_WITNESS = new Vec3(6, 65, 0)
const DOWN_ORIGIN = new Vec3(0.5, 68, 10.5)
const DOWN_WITNESS = new Vec3(0, 64, 14)
const REPEATS = 3

const verticalAims = [
  ['v_center', new Vec3(1.001, 66.45, 0.5)],
  ['v_top_center', new Vec3(1.001, 67.995, 0.5)],
  ['v_top_north_corner', new Vec3(1.001, 67.995, -0.995)],
  ['v_top_south_corner', new Vec3(1.001, 67.995, 1.995)],
  ['v_north_edge', new Vec3(1.001, 66.45, -0.995)],
  ['v_south_edge', new Vec3(1.001, 66.45, 1.995)],
  ['v_bottom_north_corner', new Vec3(1.001, 65.01, -0.995)],
  ['v_bottom_south_corner', new Vec3(1.001, 65.01, 1.995)]
]

const downAims = [
  ['d_center', new Vec3(0.5, 68.001, 10.5)],
  ['d_north_edge', new Vec3(0.5, 68.001, 9.005)],
  ['d_south_edge', new Vec3(0.5, 68.001, 11.995)],
  ['d_west_edge', new Vec3(-0.995, 68.001, 10.5)],
  ['d_east_edge', new Vec3(1.995, 68.001, 10.5)],
  ['d_nw_corner', new Vec3(-0.995, 68.001, 9.005)],
  ['d_ne_corner', new Vec3(1.995, 68.001, 9.005)],
  ['d_sw_corner', new Vec3(-0.995, 68.001, 11.995)],
  ['d_se_corner', new Vec3(1.995, 68.001, 11.995)]
]

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

async function command (bot, text, delay = 180) {
  bot.chat(text)
  await sleep(delay)
}

async function setupArena (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, '/gamemode survival PhaseBot')
  await command(bot, '/effect give PhaseBot minecraft:resistance infinite 255 true')
  await command(bot, '/effect give PhaseBot minecraft:regeneration infinite 255 true')

  await command(bot, '/fill -3 63 -3 8 70 17 minecraft:air')

  await command(bot, '/fill -2 64 -2 8 64 2 minecraft:stone')
  await command(bot, '/fill 1 65 -1 1 67 1 minecraft:obsidian')
  await command(bot, '/setblock 6 65 0 minecraft:barrel[facing=west]')

  await command(bot, '/fill -2 63 8 2 63 15 minecraft:stone')
  await command(bot, '/fill -1 67 9 1 67 11 minecraft:obsidian')
  await command(bot, '/fill -1 64 9 1 66 11 minecraft:air')
  await command(bot, '/setblock 0 64 14 minecraft:barrel[facing=north]')

  await command(bot, '/give PhaseBot minecraft:ender_pearl 64')
  await sleep(900)
}

async function reset (bot, origin) {
  const packetPromise = onceWithTimeout(bot._client, 'position', 4000)
  bot.chat(`/tp PhaseBot ${origin.x} ${origin.y} ${origin.z}`)
  const event = await packetPromise
  if (!event) throw new Error(`Reset position packet missing for ${origin}`)
  await sleep(200)
  const error = bot.entity.position.distanceTo(origin)
  if (error > 0.3) throw new Error(`Reset mismatch ${bot.entity.position}, expected ${origin}, error=${error.toFixed(3)}`)
}

async function ensurePearl (bot) {
  let pearl = bot.inventory.items().find(item => item.name === 'ender_pearl')
  if (!pearl) {
    await command(bot, '/give PhaseBot minecraft:ender_pearl 64', 500)
    pearl = bot.inventory.items().find(item => item.name === 'ender_pearl')
  }
  if (!pearl) throw new Error('Ender pearl was not present after /give')
  await bot.equip(pearl, 'hand')
  await sleep(150)
}

async function verifyWitness (bot, witnessPos) {
  const block = bot.blockAt(witnessPos)
  if (!block || block.name !== 'barrel') return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  const openedPromise = onceWithTimeout(bot, 'windowOpen', 1400)
  try {
    await bot.lookAt(witnessPos.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  const opened = await openedPromise
  if (!opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

function packetCoords (packet) {
  return {
    x: packet.x ?? null,
    y: packet.y ?? null,
    z: packet.z ?? null,
    flags: packet.flags ?? null,
    teleportId: packet.teleportId ?? null
  }
}

async function throwTrial (bot, family, name, aim, repeat) {
  const origin = family === 'vertical' ? VERTICAL_ORIGIN : DOWN_ORIGIN
  const witnessPos = family === 'vertical' ? VERTICAL_WITNESS : DOWN_WITNESS
  await reset(bot, origin)
  await ensurePearl(bot)
  await bot.lookAt(aim, true)
  await sleep(120)

  const started = process.hrtime.bigint()
  const teleportPromise = onceWithTimeout(bot._client, 'position', 6500)
  bot.activateItem()
  const args = await teleportPromise
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6
  await sleep(180)

  if (!args) {
    await sleep(1100)
    return {
      family, name, repeat, aim, elapsedMs, packet: null,
      final: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z },
      crossed: false,
      witness: { opened: false, reason: 'no_teleport_packet' }
    }
  }

  const packet = args[0]
  const final = { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
  const crossed = family === 'vertical'
    ? final.x > 2.30
    : final.y < 66.70
  const witness = crossed
    ? await verifyWitness(bot, witnessPos)
    : { opened: false, reason: 'not_crossed' }

  await sleep(1100)
  return { family, name, repeat, aim, elapsedMs, packet: packetCoords(packet), final, crossed, witness }
}

function writeReport (results, bot) {
  const report = {
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      repeats: REPEATS,
      verticalOrigin: VERTICAL_ORIGIN,
      downOrigin: DOWN_ORIGIN
    },
    results
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'pearl-report.json'), JSON.stringify(report, null, 2))

  const rows = ['family,aim,repeat,elapsed_ms,final_x,final_y,final_z,crossed,witness_open,witness_reason']
  for (const r of results) {
    rows.push([
      r.family, r.name, r.repeat, r.elapsedMs.toFixed(3),
      r.final.x.toFixed(6), r.final.y.toFixed(6), r.final.z.toFixed(6),
      r.crossed, r.witness.opened, r.witness.reason
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'pearl-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab pearl matrix complete')
  } catch (_) {
  }
  await sleep(300)
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
  bot.on('kicked', reason => console.error('[pearl kicked]', reason))
  bot.on('error', error => console.error('[pearl bot error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Pearl bot did not spawn')
    bot.physicsEnabled = false
    await sleep(1000)
    await setupArena(bot)

    const results = []
    for (const [name, aim] of verticalAims) {
      for (let repeat = 1; repeat <= REPEATS; repeat++) {
        const result = await throwTrial(bot, 'vertical', name, aim, repeat)
        results.push(result)
        console.log(`[PearlLab] ${name} #${repeat}: final=${result.final.x.toFixed(3)},${result.final.y.toFixed(3)},${result.final.z.toFixed(3)} crossed=${result.crossed} witness=${result.witness.opened}`)
      }
    }
    for (const [name, aim] of downAims) {
      for (let repeat = 1; repeat <= REPEATS; repeat++) {
        const result = await throwTrial(bot, 'down', name, aim, repeat)
        results.push(result)
        console.log(`[PearlLab] ${name} #${repeat}: final=${result.final.x.toFixed(3)},${result.final.y.toFixed(3)},${result.final.z.toFixed(3)} crossed=${result.crossed} witness=${result.witness.opened}`)
      }
    }

    writeReport(results, bot)
    const crossed = results.filter(r => r.crossed)
    const verified = results.filter(r => r.witness.opened)
    console.log(`[PearlLab] completed=${results.length} crossed=${crossed.length} witnessVerified=${verified.length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[PearlLab fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
