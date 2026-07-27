'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const RESET_X = -1.25
const BOAT_X = -0.80
const BORDER_TARGET = 0.20
const Y = 65
const Z = 0.50
const STEP = 0.25
const TICK_MS = 50
const SHORT_TARGET = 16.72
const LONG_TARGET = 240.72
const COURSE_END = 239.999
const SHIFT_FRAMES = 20

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

function waitForPrefix (bot, prefix, timeoutMs = 2200) {
  return new Promise(resolve => {
    let settled = false
    const timer = setTimeout(() => finish(null), timeoutMs)
    const handler = message => {
      const text = String(message)
      const index = text.indexOf(prefix)
      if (index >= 0) finish(text.slice(index))
    }
    function finish (value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      bot.removeListener('messagestr', handler)
      resolve(value)
    }
    bot.on('messagestr', handler)
  })
}

async function command (bot, text, delay = 100) {
  bot.chat(text)
  await sleep(delay)
}

async function serverSnapshot (bot) {
  const linePromise = waitForPrefix(bot, 'COURSE_SNAPSHOT ', 2500)
  bot.chat('/courselab snapshot')
  const line = await linePromise
  if (!line) return { ok: false, line: null }
  const match = line.match(/player=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?) health=(-?\d+(?:\.\d+)?) fire=(-?\d+) vehicle=(none|-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?)/)
  if (!match) return { ok: false, line }
  return {
    ok: true,
    line,
    position: { x: Number(match[1]), y: Number(match[2]), z: Number(match[3]) },
    health: Number(match[4]),
    fire: Number(match[5]),
    vehicle: match[6]
  }
}

async function setup (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, '/claimlab zone 0 239.999')
  await command(bot, '/courselab build mixed', 3000)
}

async function reset (bot) {
  bot.chat('/ride @s dismount')
  await sleep(250)
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 150)
  bot.vehicle = null
  const positionPromise = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s ${RESET_X} ${Y} ${Z}`)
  if (!await positionPromise) throw new Error('Reset position packet missing')
  await command(bot, '/claimlab reset', 60)
  await command(bot, '/courselab reset', 60)
  await command(bot, '/claimlab mode likely', 60)
  await command(bot, `/claimlab relation ${USERNAME} enemy`, 60)
}

async function mountBoat (bot) {
  bot.chat(`/summon minecraft:oak_boat ${BOAT_X} ${Y} ${Z} {Rotation:[-90f,0f]}`)
  await sleep(180)
  const mountPromise = onceWithTimeout(bot, 'mount', 1800)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mountPromise
  await sleep(200)
  const snapshot = await serverSnapshot(bot)
  return {
    boat: bot.vehicle || null,
    snapshot,
    serverMounted: snapshot.ok && snapshot.vehicle !== 'none'
  }
}

function writeVehicleMove (bot, boat, x) {
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
}

async function borderHandshake (bot, boat) {
  for (const x of [-0.55, -0.30, -0.05]) {
    writeVehicleMove(bot, boat, x)
    await sleep(TICK_MS)
  }
  const correctionPromise = onceWithTimeout(bot._client, 'position', 2500)
  writeVehicleMove(bot, boat, BORDER_TARGET)
  const correction = await correctionPromise
  await sleep(180)
  const snapshot = await serverSnapshot(bot)
  return {
    correctionReceived: Boolean(correction),
    correctionPacket: correction ? correction[0] : null,
    snapshot,
    stillServerMounted: snapshot.ok && snapshot.vehicle !== 'none'
  }
}

function captureCorrections (bot) {
  const player = []
  const vehicle = []
  const playerHandler = packet => player.push(packet)
  const vehicleHandler = packet => vehicle.push(packet)
  bot._client.on('position', playerHandler)
  bot._client.on('vehicle_move', vehicleHandler)
  return {
    player,
    vehicle,
    stop () {
      bot._client.removeListener('position', playerHandler)
      bot._client.removeListener('vehicle_move', vehicleHandler)
    }
  }
}

async function burstTo (bot, boat, targetX, batchSize) {
  const corrections = captureCorrections(bot)
  let x = BORDER_TARGET + STEP
  let packets = 0
  let ticks = 0
  const started = process.hrtime.bigint()

  while (x < targetX - 1e-9 && bot.vehicle && bot.entities[boat.id]) {
    let sent = 0
    while (sent < batchSize && x < targetX - 1e-9 && bot.vehicle && bot.entities[boat.id]) {
      writeVehicleMove(bot, boat, x)
      x += STEP
      packets++
      sent++
    }
    ticks++
    await sleep(TICK_MS)
  }

  if (bot.vehicle && bot.entities[boat.id]) {
    writeVehicleMove(bot, boat, targetX)
    packets++
    await sleep(150)
  }

  corrections.stop()
  const snapshot = await serverSnapshot(bot)
  return {
    packets,
    ticks,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    playerCorrections: corrections.player.length,
    vehicleCorrections: corrections.vehicle.length,
    snapshot
  }
}

async function dismountWithTickEnd (bot) {
  for (let frame = 0; frame < SHIFT_FRAMES; frame++) {
    bot._client.write('player_input', { inputs: { shift: true } })
    bot._client.write('tick_end', {})
    await sleep(TICK_MS)
  }
  bot._client.write('player_input', { inputs: {} })
  bot._client.write('tick_end', {})
  await sleep(250)
  const snapshot = await serverSnapshot(bot)
  const serverDismounted = snapshot.ok && snapshot.vehicle === 'none'
  if (serverDismounted) bot.vehicle = null
  return {
    serverDismounted,
    snapshot
  }
}

async function openWitness (bot, position) {
  await command(bot, `/setblock ${position.x} ${position.y} ${position.z} minecraft:barrel[facing=west]`, 100)
  let block = bot.blockAt(position)
  for (let attempt = 0; attempt < 20 && (!block || block.name !== 'barrel'); attempt++) {
    await sleep(100)
    block = bot.blockAt(position)
  }
  if (!block || block.name !== 'barrel') return { opened: false, reason: 'missing' }
  const openedPromise = onceWithTimeout(bot, 'windowOpen', 1800)
  try {
    await bot.lookAt(position.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  const opened = Boolean(await openedPromise)
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened, reason: opened ? 'window_open' : 'no_window' }
}

async function runTrial (bot, plan, id) {
  await reset(bot)
  const mount = await mountBoat(bot)
  if (!mount.serverMounted || !mount.boat) {
    return { ...plan, id, mount, verified: false, reason: 'server_mount_failed' }
  }

  await command(bot, `/courselab start ratchet-v2-${id}`, 80)
  const handshake = await borderHandshake(bot, mount.boat)
  const burst = await burstTo(bot, mount.boat, plan.targetX, plan.batchSize)
  const witnessPosition = plan.targetX > 100
    ? new Vec3(244, 65, 0)
    : new Vec3(Math.floor(plan.targetX) + 3, 65, 0)
  const mountedWitness = await openWitness(bot, witnessPosition)
  const dismount = await dismountWithTickEnd(bot)
  const exitWitness = await openWitness(bot, witnessPosition)
  await command(bot, '/courselab stop', 80)

  const requiredX = plan.targetX > 100 ? COURSE_END + 0.50 : plan.targetX - 0.50
  const mountedBeyond = burst.snapshot.ok && burst.snapshot.position.x >= requiredX
  const exitBeyond = dismount.snapshot.ok && dismount.snapshot.position.x >= requiredX
  return {
    ...plan,
    id,
    mount,
    handshake,
    burst,
    witnessPosition,
    mountedWitness,
    dismount,
    exitWitness,
    mountedVerified: mountedBeyond && mountedWitness.opened,
    exitVerified: dismount.serverDismounted && exitBeyond && exitWitness.opened,
    verified: mountedBeyond && mountedWitness.opened
      && dismount.serverDismounted && exitBeyond && exitWitness.opened
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'ratchet-burst-v2-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['id,target_x,batch,server_mounted,handshake_correction,handshake_vehicle,packets,ticks,burst_ms,player_corrections,vehicle_corrections,mounted_x,mounted_vehicle,mounted_health,mounted_witness,server_dismounted,exit_x,exit_vehicle,exit_health,exit_witness,mounted_verified,exit_verified,verified']
  for (const result of results) {
    rows.push([
      result.id,
      result.targetX,
      result.batchSize,
      result.mount?.serverMounted ?? '',
      result.handshake?.correctionReceived ?? '',
      result.handshake?.snapshot?.vehicle ?? '',
      result.burst?.packets ?? '',
      result.burst?.ticks ?? '',
      result.burst ? result.burst.elapsedMs.toFixed(3) : '',
      result.burst?.playerCorrections ?? '',
      result.burst?.vehicleCorrections ?? '',
      result.burst?.snapshot?.position?.x?.toFixed(6) ?? '',
      result.burst?.snapshot?.vehicle ?? '',
      result.burst?.snapshot?.health ?? '',
      result.mountedWitness?.opened ?? '',
      result.dismount?.serverDismounted ?? '',
      result.dismount?.snapshot?.position?.x?.toFixed(6) ?? '',
      result.dismount?.snapshot?.vehicle ?? '',
      result.dismount?.snapshot?.health ?? '',
      result.exitWitness?.opened ?? '',
      result.mountedVerified ?? false,
      result.exitVerified ?? false,
      result.verified ?? false
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'ratchet-burst-v2-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('Ratchet burst v2 complete')
  } catch (_) {}
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
  bot.on('kicked', reason => console.error('[RatchetBurstV2 kicked]', reason))
  bot.on('error', error => console.error('[RatchetBurstV2 error]', error))

  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setup(bot)

    const results = []
    for (const batchSize of [8, 10, 16, 20]) {
      const result = await runTrial(bot, { targetX: SHORT_TARGET, batchSize }, results.length)
      results.push(result)
      writeReport(results, bot)
      console.log(`[RatchetBurstV2] short batch=${batchSize}` +
        ` mountedX=${result.burst?.snapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` mountedWitness=${result.mountedWitness?.opened ?? false}` +
        ` dismounted=${result.dismount?.serverDismounted ?? false}` +
        ` exitX=${result.dismount?.snapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` exitWitness=${result.exitWitness?.opened ?? false}` +
        ` VERIFIED=${result.verified ?? false}`)
    }

    const successful = results.filter(result => result.verified)
      .sort((a, b) => b.batchSize - a.batchSize)
    if (successful.length > 0) {
      const longResult = await runTrial(
        bot,
        { targetX: LONG_TARGET, batchSize: successful[0].batchSize },
        results.length
      )
      results.push(longResult)
      writeReport(results, bot)
      console.log(`[RatchetBurstV2] LONG batch=${longResult.batchSize}` +
        ` mountedX=${longResult.burst?.snapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` mountedWitness=${longResult.mountedWitness?.opened ?? false}` +
        ` dismounted=${longResult.dismount?.serverDismounted ?? false}` +
        ` exitX=${longResult.dismount?.snapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` exitWitness=${longResult.exitWitness?.opened ?? false}` +
        ` VERIFIED=${longResult.verified ?? false}`)
    }

    console.log(`[RatchetBurstV2] completed=${results.length}` +
      ` mountedVerified=${results.filter(result => result.mountedVerified).length}` +
      ` exitVerified=${results.filter(result => result.exitVerified).length}` +
      ` fullyVerified=${results.filter(result => result.verified).length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[RatchetBurstV2 fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
