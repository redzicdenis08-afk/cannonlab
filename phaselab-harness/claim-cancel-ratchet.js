'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const START_X = -0.80
const RESET_X = -1.25
const Y = 65
const Z = 0.50
const STEP = 0.25
const CLAIM_MIN = 0
const CLAIM_MAX = 15.999
const TARGETS = [0.20, 1.20, 2.20, 4.20, 8.20, 16.72]

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

async function command (bot, text, delay = 100) {
  bot.chat(text)
  await sleep(delay)
}

async function setupArena (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, '/fill -5 63 -4 22 72 4 minecraft:air', 250)
  await command(bot, '/fill -5 64 -4 22 64 4 minecraft:stone', 180)
  await command(bot, '/fill 0 65 -3 15 69 3 minecraft:obsidian', 450)
  for (let x = 1; x <= 15; x += 2) {
    await command(bot, `/fill ${x} 65 -3 ${x} 69 3 minecraft:water`, 35)
  }
  await command(bot, `/claimlab zone ${CLAIM_MIN} ${CLAIM_MAX}`)
}

async function reset (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 900)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 80)
  const position = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat(`/tp @s ${RESET_X} ${Y} ${Z}`)
  if (!await position) throw new Error('Reset teleport missing')
  await command(bot, '/claimlab reset', 60)
}

async function configure (bot, mode) {
  await command(bot, `/claimlab mode ${mode}`)
  await command(bot, `/claimlab relation ${USERNAME} enemy`)
}

async function mountBoat (bot) {
  bot.chat(`/summon minecraft:oak_boat ${START_X} ${Y} ${Z} {Rotation:[-90f,0f],Invulnerable:1b}`)
  await sleep(130)
  const mounted = onceWithTimeout(bot, 'mount', 1600)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  await sleep(100)
  return bot.vehicle || null
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

async function authoritativeBoatSnapshot (bot, boat) {
  const teleportPromise = onceWithTimeout(bot._client, 'entity_teleport', 1400)
  bot.chat('/tp @e[type=minecraft:oak_boat,limit=1] ~ ~ ~')
  const args = await teleportPromise
  await sleep(70)
  return {
    packet: args ? args[0] : null,
    position: boat
      ? { x: boat.position.x, y: boat.position.y, z: boat.position.z }
      : null
  }
}

async function authoritativePlayerSnapshot (bot) {
  const packetPromise = onceWithTimeout(bot._client, 'position', 1800)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  await sleep(80)
  return {
    packet: args ? packetPosition(args[0]) : null,
    position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
  }
}

async function ratchetTo (bot, boat, targetX, strategy) {
  const corrections = []
  const vehicleCorrections = []
  const started = process.hrtime.bigint()
  const playerHandler = packet => corrections.push({
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    packet: packetPosition(packet)
  })
  const vehicleHandler = packet => vehicleCorrections.push({
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    packet
  })
  bot._client.on('position', playerHandler)
  bot._client.on('vehicle_move', vehicleHandler)

  let x = START_X + STEP
  let packets = 0
  const checkpoints = []
  while (x < targetX - 1e-9 && bot.vehicle) {
    const beforeCorrections = corrections.length
    boat.position.set(x, Y, Z)
    bot.entity.position.set(x, Y, Z)
    bot._client.write('vehicle_move', {
      x,
      y: Y,
      z: Z,
      yaw: -90,
      pitch: 0,
      onGround: true
    })
    packets++

    const waitMs = strategy === 'slow_ack' ? 120 : 65
    await sleep(waitMs)
    const corrected = corrections.length > beforeCorrections
    if (corrected && strategy === 'pause_after_correction') {
      await sleep(100)
    }

    if (packets <= 8 || packets % 8 === 0 || x + STEP >= targetX) {
      const snapshot = await authoritativeBoatSnapshot(bot, boat)
      checkpoints.push({
        requestedX: x,
        corrected,
        playerCorrections: corrections.length,
        vehicleCorrections: vehicleCorrections.length,
        boat: snapshot.position,
        mounted: Boolean(bot.vehicle)
      })
    }
    x += STEP
  }

  if (bot.vehicle && x >= targetX - 1e-9) {
    boat.position.set(targetX, Y, Z)
    bot.entity.position.set(targetX, Y, Z)
    bot._client.write('vehicle_move', {
      x: targetX,
      y: Y,
      z: Z,
      yaw: -90,
      pitch: 0,
      onGround: true
    })
    packets++
    await sleep(strategy === 'slow_ack' ? 150 : 90)
  }

  bot._client.removeListener('position', playerHandler)
  bot._client.removeListener('vehicle_move', vehicleHandler)
  const finalBoat = await authoritativeBoatSnapshot(bot, boat)
  return {
    packets,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    corrections,
    vehicleCorrections,
    checkpoints,
    finalBoat
  }
}

async function dismountAndVerify (bot, targetX) {
  let dismounted = false
  if (bot.vehicle) {
    const dismountPromise = onceWithTimeout(bot, 'dismount', 1800)
    bot.dismount()
    dismounted = Boolean(await dismountPromise)
  }
  await sleep(250)
  const player = await authoritativePlayerSnapshot(bot)
  const witnessPos = new Vec3(Math.floor(targetX) + 3, 65, 0)
  await command(bot, `/setblock ${witnessPos.x} ${witnessPos.y} ${witnessPos.z} minecraft:barrel[facing=west]`, 80)
  const insideAtDepth = player.position.x >= Math.max(0.05, targetX - 1.75)
  let witness = { opened: false, reason: 'not_at_depth' }
  if (insideAtDepth) {
    let block = bot.blockAt(witnessPos)
    for (let attempt = 0; attempt < 12 && (!block || block.name !== 'barrel'); attempt++) {
      await sleep(80)
      block = bot.blockAt(witnessPos)
    }
    if (block && block.name === 'barrel') {
      const opened = onceWithTimeout(bot, 'windowOpen', 1300)
      try {
        await bot.lookAt(witnessPos.offset(0.5, 0.5, 0.5), true)
        await bot.activateBlock(block)
        witness = await opened
          ? { opened: true, reason: 'window_open' }
          : { opened: false, reason: 'no_window_open' }
        if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
      } catch (error) {
        witness = { opened: false, reason: `activate:${error.message}` }
      }
    } else {
      witness = { opened: false, reason: 'missing_witness' }
    }
  }
  return {
    dismounted,
    player,
    insideAtDepth,
    witness,
    verified: dismounted && insideAtDepth && witness.opened
  }
}

async function runTrial (bot, plan, id) {
  await reset(bot)
  await configure(bot, plan.mode)
  const boat = await mountBoat(bot)
  if (!boat) {
    return { ...plan, id, mounted: false, verified: false, reason: 'mount_failed' }
  }
  const ratchet = await ratchetTo(bot, boat, plan.targetX, plan.strategy)
  const dismount = await dismountAndVerify(bot, plan.targetX)
  return {
    ...plan,
    id,
    mounted: true,
    stillMountedBeforeDismount: Boolean(bot.vehicle),
    ratchet,
    dismount,
    verified: dismount.verified
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'claim-ratchet-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      step: STEP,
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['id,mode,strategy,target_x,mounted,packets,elapsed_ms,player_corrections,vehicle_corrections,boat_x,dismounted,player_x,inside_depth,witness,verified']
  for (const result of results) {
    rows.push([
      result.id,
      result.mode,
      result.strategy,
      result.targetX,
      result.mounted,
      result.ratchet ? result.ratchet.packets : '',
      result.ratchet ? result.ratchet.elapsedMs.toFixed(3) : '',
      result.ratchet ? result.ratchet.corrections.length : '',
      result.ratchet ? result.ratchet.vehicleCorrections.length : '',
      result.ratchet?.finalBoat?.position?.x?.toFixed(6) ?? '',
      result.dismount?.dismounted ?? '',
      result.dismount?.player?.position?.x?.toFixed(6) ?? '',
      result.dismount?.insideAtDepth ?? '',
      result.dismount?.witness?.opened ?? '',
      result.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'claim-ratchet-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab claim ratchet complete')
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
  bot.on('kicked', reason => console.error('[ClaimRatchet kicked]', reason))
  bot.on('error', error => console.error('[ClaimRatchet error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Claim ratchet bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setupArena(bot)

    const plans = []
    for (const strategy of ['ack_each', 'pause_after_correction', 'slow_ack']) {
      for (const targetX of TARGETS) {
        plans.push({ mode: 'likely', strategy, targetX })
      }
    }
    for (const targetX of [1.20, 4.20, 16.72]) {
      plans.push({ mode: 'strict', strategy: 'ack_each', targetX })
    }

    const results = []
    for (let id = 0; id < plans.length; id++) {
      const result = await runTrial(bot, plans[id], id)
      results.push(result)
      writeReport(results, bot)
      console.log(`[ClaimRatchet] ${id + 1}/${plans.length}` +
        ` mode=${result.mode} strategy=${result.strategy} target=${result.targetX}` +
        ` boatX=${result.ratchet?.finalBoat?.position?.x?.toFixed(3) ?? 'none'}` +
        ` corrections=${result.ratchet?.corrections?.length ?? 0}` +
        ` playerX=${result.dismount?.player?.position?.x?.toFixed(3) ?? 'none'}` +
        ` verified=${result.verified}`)
    }

    const verified = results.filter(result => result.verified).length
    console.log(`[ClaimRatchet] completed=${results.length} verified=${verified}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[ClaimRatchet fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
