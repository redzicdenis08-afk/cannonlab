'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const WALL_MIN_X = 1
const WALL_MAX_X = 2
const FULLY_BEYOND_X = WALL_MAX_X + 0.301
const WITNESS = new Vec3(4, 65, 0)
const RESET_X = -1.25
const Y = 65

const BOAT_X = [0.20, 0.30, 0.31]
const MINECART_X = [0.45, 0.50]
const Z_SEAMS = [0.01, 0.50, 0.99]
const YAWS = [0, 45, 90, 135, 180, 225, 270, 315]

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

async function command (bot, text, delay = 140) {
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
  await sleep(500)
}

async function reset (bot, z) {
  if (bot.vehicle) {
    bot._client.write('player_input', { inputs: { shift: true } })
    await onceWithTimeout(bot, 'dismount', 1200)
  }

  await command(bot, '/kill @e[type=minecraft:oak_boat]')
  await command(bot, '/kill @e[type=minecraft:minecart]')

  const packetPromise = onceWithTimeout(bot._client, 'position', 3000)
  bot.chat(`/tp @s ${RESET_X} ${Y} ${z}`)
  const packet = await packetPromise
  if (!packet) throw new Error(`Reset position packet missing at z=${z}`)
  await sleep(180)
}

function vehicleMatch (family) {
  return entity => {
    const name = String(entity.name || '').toLowerCase()
    return family === 'boat' ? name.includes('boat') : name.includes('minecart')
  }
}

async function summonVehicle (bot, family, x, z, yaw) {
  const match = vehicleMatch(family)
  const spawnPromise = waitForEntity(bot, match, 2500)
  const entityId = family === 'boat' ? 'minecraft:oak_boat' : 'minecraft:minecart'
  bot.chat(`/summon ${entityId} ${x} ${Y} ${z} {Rotation:[${yaw}f,0f],Invulnerable:1b}`)
  let entity = await spawnPromise
  if (!entity) {
    entity = bot.nearestEntity(match)
  }
  if (!entity) throw new Error(`No ${family} entity after summon at ${x},${Y},${z}`)
  await sleep(120)
  return entity
}

async function mountVehicle (bot, vehicle) {
  const mounted = onceWithTimeout(bot, 'mount', 2500)
  bot.mount(vehicle)
  let event = await mounted
  if (!event && !bot.vehicle) {
    await sleep(120)
    const retry = onceWithTimeout(bot, 'mount', 2500)
    bot.mount(vehicle)
    event = await retry
  }
  if (!bot.vehicle) throw new Error(`Mount failed for entity ${vehicle.name}#${vehicle.id}`)
  await sleep(180)
}

async function driveIntoWall (bot, durationMs) {
  bot.moveVehicle(0, 1)
  await sleep(durationMs)
  bot.moveVehicle(0, 0)
  await sleep(100)
}

async function dismountVehicle (bot) {
  const packets = []
  const started = process.hrtime.bigint()
  const positionHandler = packet => {
    packets.push({
      elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
      x: packet.x ?? null,
      y: packet.y ?? null,
      z: packet.z ?? null,
      flags: packet.flags ?? null,
      teleportId: packet.teleportId ?? null
    })
  }
  bot._client.on('position', positionHandler)

  let dismounted = onceWithTimeout(bot, 'dismount', 1800)
  bot.dismount()
  let event = await dismounted

  if (!event && bot.vehicle) {
    dismounted = onceWithTimeout(bot, 'dismount', 1800)
    bot._client.write('player_input', { inputs: { shift: true } })
    event = await dismounted
    bot._client.write('player_input', { inputs: { shift: false } })
  }

  await sleep(450)
  bot._client.removeListener('position', positionHandler)
  if (bot.vehicle) throw new Error('Vehicle remained mounted after dismount attempts')
  return packets
}

async function verifyWitness (bot) {
  const block = bot.blockAt(WITNESS)
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  }

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

async function authoritativeSnapshot (bot) {
  const packetPromise = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  if (!args) {
    return {
      packet: null,
      position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z },
      reason: 'no_snapshot_packet'
    }
  }
  await sleep(100)
  const packet = args[0]
  return {
    packet: {
      x: packet.x ?? null,
      y: packet.y ?? null,
      z: packet.z ?? null,
      flags: packet.flags ?? null,
      teleportId: packet.teleportId ?? null
    },
    position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z },
    reason: 'self_tp_snapshot'
  }
}

async function runTrial (bot, spec) {
  await reset(bot, spec.z)
  const vehicle = await summonVehicle(bot, spec.family, spec.x, spec.z, spec.yaw)
  await mountVehicle(bot, vehicle)

  if (spec.driveMs > 0) await driveIntoWall(bot, spec.driveMs)

  const preDismount = {
    player: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z },
    vehicle: bot.vehicle
      ? { x: bot.vehicle.position.x, y: bot.vehicle.position.y, z: bot.vehicle.position.z }
      : null
  }

  const packets = await dismountVehicle(bot)
  const clientFinal = { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
  const witness = await verifyWitness(bot)
  const snapshot = await authoritativeSnapshot(bot)
  const final = snapshot.position

  const fullyBeyond = final.x > FULLY_BEYOND_X
  const wallOverlap = final.x > WALL_MIN_X - 0.30 && final.x < WALL_MAX_X + 0.30
  const verified = fullyBeyond && witness.opened

  return {
    ...spec,
    preDismount,
    packets,
    clientFinal,
    snapshot,
    fullyBeyond,
    wallOverlap,
    witness,
    verified
  }
}

function buildTrials () {
  const trials = []
  for (const x of BOAT_X) {
    for (const z of Z_SEAMS) {
      for (const yaw of YAWS) {
        trials.push({ family: 'boat', mode: 'static', x, z, yaw, driveMs: 0 })
      }
    }
  }
  for (const x of MINECART_X) {
    for (const z of Z_SEAMS) {
      for (const yaw of YAWS) {
        trials.push({ family: 'minecart', mode: 'static', x, z, yaw, driveMs: 0 })
      }
    }
  }

  // A boat facing east (+X wall direction) while actively driven into the wall.
  for (const x of [0.0, 0.20, 0.30]) {
    for (const z of Z_SEAMS) {
      for (const driveMs of [150, 400, 900]) {
        trials.push({ family: 'boat', mode: 'drive_into_wall', x, z, yaw: -90, driveMs })
      }
    }
  }
  return trials
}

function writeReport (results, bot) {
  const report = {
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      wall: { minX: WALL_MIN_X, maxX: WALL_MAX_X, fullyBeyondX: FULLY_BEYOND_X },
      witness: WITNESS,
      trialCount: results.length
    },
    results
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-report.json'), JSON.stringify(report, null, 2))

  const rows = ['family,mode,x,z,yaw,drive_ms,final_x,final_y,final_z,fully_beyond,wall_overlap,witness_open,verified,position_packets,first_packet_ms,witness_reason']
  for (const r of results) {
    const first = r.packets[0]
    rows.push([
      r.family, r.mode, r.x, r.z, r.yaw, r.driveMs,
      r.snapshot.position.x.toFixed(6), r.snapshot.position.y.toFixed(6), r.snapshot.position.z.toFixed(6),
      r.fullyBeyond, r.wallOverlap, r.witness.opened, r.verified,
      r.packets.length, first ? first.elapsedMs.toFixed(3) : '', r.witness.reason
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab vehicle matrix complete')
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

  bot.on('kicked', reason => console.error('[VehicleLab kicked]', reason))
  bot.on('error', error => console.error('[VehicleLab bot error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Vehicle bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setupArena(bot)

    const trials = buildTrials()
    const results = []
    for (let index = 0; index < trials.length; index++) {
      const spec = trials[index]
      const result = await runTrial(bot, spec)
      results.push(result)
      console.log(
        `[VehicleLab] ${index + 1}/${trials.length} ${spec.family}/${spec.mode}` +
        ` x=${spec.x} z=${spec.z} yaw=${spec.yaw} drive=${spec.driveMs}` +
        ` final=${result.snapshot.position.x.toFixed(3)},${result.snapshot.position.y.toFixed(3)},${result.snapshot.position.z.toFixed(3)}` +
        ` beyond=${result.fullyBeyond} witness=${result.witness.opened} verified=${result.verified}`
      )
    }

    writeReport(results, bot)
    const beyond = results.filter(r => r.fullyBeyond)
    const overlap = results.filter(r => r.wallOverlap)
    const verified = results.filter(r => r.verified)
    console.log(`[VehicleLab] completed=${results.length} beyond=${beyond.length} overlap=${overlap.length} verified=${verified.length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[VehicleLab fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
