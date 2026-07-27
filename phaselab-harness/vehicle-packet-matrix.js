'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const START_X = 0.20
const TARGET_X = 2.72
const Y = 65
const RESET_X = -1.25
const Z_SEAMS = [0.01, 0.50, 0.99]
const WITNESS = new Vec3(4, 65, 0)

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

function waitForEntity (bot, predicate, timeoutMs = 2500) {
  return new Promise(resolve => {
    let settled = false
    const timer = setTimeout(() => finish(null), timeoutMs)
    const handler = entity => {
      if (predicate(entity)) finish(entity)
    }
    function finish (value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      bot.removeListener('entitySpawn', handler)
      resolve(value)
    }
    bot.on('entitySpawn', handler)
  })
}

async function command (bot, text, delay = 120) {
  bot.chat(text)
  await sleep(delay)
}

async function setupArena (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, '/fill -5 63 -10 8 72 10 minecraft:air')
  await command(bot, '/fill -4 64 -9 7 64 9 minecraft:stone')
  await command(bot, '/fill 1 65 -7 1 69 7 minecraft:obsidian')
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`)
  await sleep(400)
}

async function reset (bot, z) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 1800)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]')
  const packetPromise = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s ${RESET_X} ${Y} ${z}`)
  if (!await packetPromise) throw new Error(`Reset packet missing at z=${z}`)
  await sleep(150)
}

async function summonAndMount (bot, z) {
  const match = entity => String(entity.name || '').toLowerCase().includes('boat')
  const spawnPromise = waitForEntity(bot, match, 2500)
  bot.chat(`/summon minecraft:oak_boat ${START_X} ${Y} ${z} {Rotation:[-90f,0f],Invulnerable:1b}`)
  let boat = await spawnPromise
  if (!boat) boat = bot.nearestEntity(match)
  if (!boat) throw new Error('Boat did not spawn')

  let mounted = onceWithTimeout(bot, 'mount', 2500)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  if (!bot.vehicle) {
    mounted = onceWithTimeout(bot, 'mount', 2500)
    bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
    await mounted
  }
  if (!bot.vehicle) throw new Error('Boat ride fixture failed')
  await sleep(180)
  return boat
}

function buildTrials () {
  const variants = [
    { name: 'direct', step: TARGET_X - START_X, delayMs: 0, yOffset: 0 },
    { name: 'step_0_50_50ms', step: 0.50, delayMs: 50, yOffset: 0 },
    { name: 'step_0_25_50ms', step: 0.25, delayMs: 50, yOffset: 0 },
    { name: 'step_0_10_50ms', step: 0.10, delayMs: 50, yOffset: 0 },
    { name: 'step_0_25_100ms', step: 0.25, delayMs: 100, yOffset: 0 },
    { name: 'step_0_25_y_0_0625', step: 0.25, delayMs: 50, yOffset: 0.0625 },
    { name: 'step_0_25_y_0_25', step: 0.25, delayMs: 50, yOffset: 0.25 }
  ]
  const trials = []
  for (const z of Z_SEAMS) {
    for (const variant of variants) {
      for (const onGround of [false, true]) {
        trials.push({ ...variant, z, onGround })
      }
    }
  }
  return trials
}

function makeSequence (spec) {
  const sequence = []
  const distance = TARGET_X - START_X
  if (spec.step >= distance) {
    sequence.push(TARGET_X)
    return sequence
  }
  for (let moved = spec.step; moved < distance - 1e-7; moved += spec.step) {
    sequence.push(START_X + moved)
  }
  sequence.push(TARGET_X)
  return sequence
}

function captureCorrections (bot, boatId) {
  const started = process.hrtime.bigint()
  const events = []
  const add = (type, packet) => {
    events.push({
      type,
      elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
      packet
    })
  }
  const vehicleMove = packet => add('vehicle_move', packet)
  const playerPosition = packet => add('player_position', packet)
  const entityTeleport = packet => {
    if (packet.entityId === boatId) add('boat_entity_teleport', packet)
  }
  const passengers = packet => add('set_passengers', packet)

  bot._client.on('vehicle_move', vehicleMove)
  bot._client.on('position', playerPosition)
  bot._client.on('entity_teleport', entityTeleport)
  bot._client.on('set_passengers', passengers)

  return {
    events,
    stop: () => {
      bot._client.removeListener('vehicle_move', vehicleMove)
      bot._client.removeListener('position', playerPosition)
      bot._client.removeListener('entity_teleport', entityTeleport)
      bot._client.removeListener('set_passengers', passengers)
    }
  }
}

async function sendVehicleSequence (bot, spec) {
  const sequence = makeSequence(spec)
  const y = Y + spec.yOffset
  for (const x of sequence) {
    if (!bot.vehicle) break
    bot.vehicle.position.set(x, y, spec.z)
    bot.entity.position.set(x, y, spec.z)
    bot._client.write('vehicle_move', {
      x,
      y,
      z: spec.z,
      yaw: -90,
      pitch: 0,
      onGround: spec.onGround
    })
    if (spec.delayMs > 0) await sleep(spec.delayMs)
  }
  return sequence.length
}

function waitForToken (bot, token, timeoutMs) {
  return new Promise(resolve => {
    let settled = false
    const timer = setTimeout(() => finish(false), timeoutMs)
    const handler = message => {
      if (String(message).includes(token)) finish(true)
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

async function serverBeyondCheck (bot, suffix) {
  const token = `PHASELAB_BEYOND_${suffix}_${Date.now()}`
  const seen = waitForToken(bot, token, 1200)
  bot.chat(`/execute if entity @s[x=2.301,y=64,z=-7,dx=5.699,dy=6,dz=14] run tellraw @s {"text":"${token}"}`)
  return await seen
}

async function verifyWitness (bot) {
  const block = bot.blockAt(WITNESS)
  if (!block || block.name !== 'barrel') return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  const openedPromise = onceWithTimeout(bot, 'windowOpen', 1200)
  try {
    await bot.lookAt(WITNESS.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  const opened = await openedPromise
  if (!opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function dismountAndSnapshot (bot) {
  if (bot.vehicle) {
    let dismounted = onceWithTimeout(bot, 'dismount', 1500)
    bot.dismount()
    let event = await dismounted
    if (!event && bot.vehicle) {
      dismounted = onceWithTimeout(bot, 'dismount', 1500)
      bot._client.write('player_input', { inputs: { shift: true } })
      event = await dismounted
      bot._client.write('player_input', { inputs: { shift: false } })
    }
  }
  await sleep(250)

  const packetPromise = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  await sleep(100)
  return {
    packet: args ? args[0] : null,
    position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
  }
}

async function runTrial (bot, spec, index) {
  await reset(bot, spec.z)
  const boat = await summonAndMount(bot, spec.z)
  const capture = captureCorrections(bot, boat.id)
  const packetCount = await sendVehicleSequence(bot, spec)
  await sleep(650)

  const serverBeyondMounted = await serverBeyondCheck(bot, index)
  const mountedWitness = serverBeyondMounted
    ? await verifyWitness(bot)
    : { opened: false, reason: 'server_not_beyond' }

  capture.stop()
  const snapshot = await dismountAndSnapshot(bot)
  const postDismountWitness = snapshot.position.x > 2.301
    ? await verifyWitness(bot)
    : { opened: false, reason: 'post_dismount_not_beyond' }

  return {
    ...spec,
    packetCount,
    corrections: capture.events,
    serverBeyondMounted,
    mountedWitness,
    snapshot,
    postDismountWitness,
    verifiedMounted: serverBeyondMounted && mountedWitness.opened,
    verifiedPostDismount: snapshot.position.x > 2.301 && postDismountWitness.opened
  }
}

function writeReport (results, bot) {
  const report = {
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      startX: START_X,
      targetX: TARGET_X,
      witness: WITNESS,
      trialCount: results.length
    },
    results
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-packet-report.json'), JSON.stringify(report, null, 2))

  const rows = ['name,z,on_ground,step,delay_ms,y_offset,packet_count,corrections,first_correction_type,first_correction_ms,server_beyond_mounted,mounted_witness,post_x,post_y,post_z,post_witness,verified_mounted,verified_post']
  for (const r of results) {
    const first = r.corrections[0]
    rows.push([
      r.name, r.z, r.onGround, r.step, r.delayMs, r.yOffset, r.packetCount,
      r.corrections.length, first ? first.type : '', first ? first.elapsedMs.toFixed(3) : '',
      r.serverBeyondMounted, r.mountedWitness.opened,
      r.snapshot.position.x.toFixed(6), r.snapshot.position.y.toFixed(6), r.snapshot.position.z.toFixed(6),
      r.postDismountWitness.opened, r.verifiedMounted, r.verifiedPostDismount
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-packet-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab vehicle packet matrix complete')
  } catch (_) {
  }
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
  bot.on('kicked', reason => console.error('[VehiclePacketLab kicked]', reason))
  bot.on('error', error => console.error('[VehiclePacketLab bot error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Vehicle packet bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setupArena(bot)

    const trials = buildTrials()
    const results = []
    for (let index = 0; index < trials.length; index++) {
      const spec = trials[index]
      const result = await runTrial(bot, spec, index)
      results.push(result)
      const first = result.corrections[0]
      console.log(
        `[VehiclePacketLab] ${index + 1}/${trials.length} ${spec.name}` +
        ` z=${spec.z} ground=${spec.onGround} packets=${result.packetCount}` +
        ` corrections=${result.corrections.length}` +
        (first ? ` first=${first.type}@${first.elapsedMs.toFixed(1)}ms` : '') +
        ` mountedBeyond=${result.serverBeyondMounted}` +
        ` mountedWitness=${result.mountedWitness.opened}` +
        ` post=${result.snapshot.position.x.toFixed(3)},${result.snapshot.position.y.toFixed(3)},${result.snapshot.position.z.toFixed(3)}` +
        ` verified=${result.verifiedMounted || result.verifiedPostDismount}`
      )
    }

    writeReport(results, bot)
    const mounted = results.filter(r => r.verifiedMounted)
    const post = results.filter(r => r.verifiedPostDismount)
    const beyond = results.filter(r => r.serverBeyondMounted)
    console.log(`[VehiclePacketLab] completed=${results.length} serverBeyondMounted=${beyond.length} verifiedMounted=${mounted.length} verifiedPost=${post.length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[VehiclePacketLab fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
