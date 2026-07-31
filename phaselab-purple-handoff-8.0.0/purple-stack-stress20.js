'use strict'

// Purple-team differential reproducer for isolated loopback PhaseLab runtimes only.
// The hard endpoint lock is intentional: this packet driver must not run
// against arbitrary or public servers.

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25569)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || `output-purple-stack-${PORT}`)
const CLIENT_VERSION = process.env.PHASELAB_CLIENT_VERSION || '1.21.11'
const VEHICLE_KIND = process.env.PHASELAB_VEHICLE || 'oak_boat'
const INTERMEDIATE_KIND = process.env.PHASELAB_INTERMEDIATE || ''
const PROFILE_SET = process.env.PHASELAB_PROFILE_SET || 'overlap'
const REQUESTED_WALL_THICKNESS = Number.parseInt(process.env.PHASELAB_WALL_THICKNESS || '1', 10)
const WALL_THICKNESS = Number.isFinite(REQUESTED_WALL_THICKNESS) && REQUESTED_WALL_THICKNESS > 0
  ? Math.min(240, REQUESTED_WALL_THICKNESS)
  : 1
const DEFAULT_TARGET_X = 1.0 + WALL_THICKNESS + 0.35
const REQUESTED_TARGET_X = Number(process.env.PHASELAB_TARGET_X || DEFAULT_TARGET_X)

const ALLOWED_PORTS = new Set([25566, 25567, 25568, 25569])
if (!['127.0.0.1', 'localhost', '::1'].includes(HOST) || !ALLOWED_PORTS.has(PORT)) {
  throw new Error(`Lab lock rejected ${HOST}:${PORT}; expected loopback on 25566-25569`)
}

const START_X = 0.20
const TARGET_X = Number.isFinite(REQUESTED_TARGET_X) && REQUESTED_TARGET_X > 2.05
  ? REQUESTED_TARGET_X
  : 2.35
const Y = 65
const Z = 0.01
const WALL_MIN_X = 1.0
const WALL_MAX_X = WALL_MIN_X + WALL_THICKNESS
const WITNESS = new Vec3(Math.ceil(TARGET_X) + 3, 65, 0)
const TICK_MS = 50

const VEHICLES = {
  oak_boat: {
    selector: 'minecraft:oak_boat',
    match: 'boat',
    nbt: '{Rotation:[-90f,0f],Invulnerable:1b}'
  },
  oak_chest_boat: {
    selector: 'minecraft:oak_chest_boat',
    match: 'chest_boat',
    nbt: '{Rotation:[-90f,0f],Invulnerable:1b}'
  },
  horse: {
    selector: 'minecraft:horse',
    match: 'horse',
    nbt: '{Rotation:[-90f,0f],Tame:1b,Invulnerable:1b,SaddleItem:{id:"minecraft:saddle",count:1}}'
  },
  camel: {
    selector: 'minecraft:camel',
    match: 'camel',
    nbt: '{Rotation:[-90f,0f],Tame:1b,Invulnerable:1b,SaddleItem:{id:"minecraft:saddle",count:1}}'
  },
  pig: {
    selector: 'minecraft:pig',
    match: 'pig',
    nbt: '{Rotation:[-90f,0f],Invulnerable:1b,Saddle:1b}'
  },
  strider: {
    selector: 'minecraft:strider',
    match: 'strider',
    nbt: '{Rotation:[-90f,0f],Invulnerable:1b,Saddle:1b}'
  },
  bamboo_raft: {
    selector: 'minecraft:bamboo_raft',
    match: 'raft',
    nbt: '{Rotation:[-90f,0f],Invulnerable:1b}'
  },
  minecart: {
    selector: 'minecraft:minecart',
    match: 'minecart',
    nbt: '{Rotation:[-90f,0f],Invulnerable:1b}'
  },
  happy_ghast: {
    selector: 'minecraft:happy_ghast',
    match: 'happy_ghast',
    nbt: '{Rotation:[-90f,0f],Invulnerable:1b,NoAI:1b}'
  },
  armor_stand: {
    selector: 'minecraft:armor_stand',
    match: 'armor_stand',
    nbt: '{Rotation:[-90f,0f],Invulnerable:1b,NoGravity:1b}'
  }
}

if (!VEHICLES[VEHICLE_KIND]) {
  throw new Error(`Unknown PHASELAB_VEHICLE=${VEHICLE_KIND}`)
}
if (INTERMEDIATE_KIND && !VEHICLES[INTERMEDIATE_KIND]) {
  throw new Error(`Unknown PHASELAB_INTERMEDIATE=${INTERMEDIATE_KIND}`)
}

const OVERLAP_PROFILES = [
  { id: 'flat-005', vehicleYOffset: 0.0, playerStep: 0.05, playerYOffset: 0.0, onGround: false },
  { id: 'flat-010', vehicleYOffset: 0.0, playerStep: 0.10, playerYOffset: 0.0, onGround: false },
  { id: 'flat-020', vehicleYOffset: 0.0, playerStep: 0.20, playerYOffset: 0.0, onGround: false },
  { id: 'embed-00625-flat-005', vehicleYOffset: 0.0625, playerStep: 0.05, playerYOffset: 0.0, onGround: false },
  { id: 'embed-00625-flat-010', vehicleYOffset: 0.0625, playerStep: 0.10, playerYOffset: 0.0, onGround: false },
  { id: 'embed-025-flat-005', vehicleYOffset: 0.25, playerStep: 0.05, playerYOffset: 0.0, onGround: false },
  { id: 'embed-025-flat-010', vehicleYOffset: 0.25, playerStep: 0.10, playerYOffset: 0.0, onGround: false },
  { id: 'embed-025-lift-00625', vehicleYOffset: 0.25, playerStep: 0.05, playerYOffset: 0.0625, onGround: false },
  { id: 'embed-025-down-00625', vehicleYOffset: 0.25, playerStep: 0.05, playerYOffset: -0.0625, onGround: false },
  { id: 'embed-025-ground', vehicleYOffset: 0.25, playerStep: 0.05, playerYOffset: 0.0, onGround: true },
  { id: 'embed-050-flat-005', vehicleYOffset: 0.50, playerStep: 0.05, playerYOffset: 0.0, onGround: false },
  { id: 'embed-050-flat-010', vehicleYOffset: 0.50, playerStep: 0.10, playerYOffset: 0.0, onGround: false }
]
const FAMILY_PROFILES = [
  { id: 'family-flat-025', vehicleYOffset: 0.0, playerStep: 0.05, playerYOffset: 0.0, onGround: false },
  { id: 'family-embed-00625', vehicleYOffset: 0.0625, playerStep: 0.05, playerYOffset: 0.0, onGround: false },
  { id: 'family-embed-025', vehicleYOffset: 0.25, playerStep: 0.05, playerYOffset: 0.0, onGround: false },
  { id: 'family-embed-050', vehicleYOffset: 0.50, playerStep: 0.05, playerYOffset: 0.0, onGround: false }
]
const SMOKE_PROFILES = Array.from({ length: 20 }, (_, index) => ({ ...FAMILY_PROFILES[0], id: `family-flat-025-r${index + 1}` }))
const PROFILES = PROFILE_SET === 'smoke'
  ? SMOKE_PROFILES
  : PROFILE_SET === 'family'
    ? FAMILY_PROFILES
    : OVERLAP_PROFILES

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

function waitForPrefix (bot, prefix, timeoutMs = 2500) {
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

async function command (bot, text, delay = 120) {
  bot.chat(text)
  await sleep(delay)
}

async function snapshot (bot) {
  const linePromise = waitForPrefix(bot, 'COURSE_SNAPSHOT ')
  bot.chat('/courselab snapshot')
  const line = await linePromise
  const match = line && line.match(
    /player=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?) health=(-?\d+(?:\.\d+)?) fire=(-?\d+) vehicle=(none|-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?)/
  )
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
  await command(bot, '/claimlab mode observe')
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, '/fill -5 63 -10 8 72 10 minecraft:air')
  await command(bot, '/fill -4 64 -9 7 64 9 minecraft:stone')
  await command(bot, `/fill 1 65 -7 ${Math.ceil(WALL_MAX_X) - 1} 70 7 minecraft:obsidian`)
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`)
  await sleep(350)
}

async function reset (bot) {
  bot.chat('/ride @s dismount')
  await sleep(160)
  await command(bot, `/kill @e[type=${VEHICLES[VEHICLE_KIND].selector}]`, 140)
  if (INTERMEDIATE_KIND && INTERMEDIATE_KIND !== VEHICLE_KIND) {
    await command(bot, `/kill @e[type=${VEHICLES[INTERMEDIATE_KIND].selector}]`, 100)
  }
  bot.vehicle = null
  const positioned = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s -1.25 ${Y} ${Z}`)
  if (!await positioned) throw new Error('Reset position packet missing')
  await sleep(150)
}

async function mountBoat (bot) {
  const spec = VEHICLES[VEHICLE_KIND]
  bot.chat(`/summon ${spec.selector} ${START_X} ${Y} ${Z} ${spec.nbt}`)
  await sleep(200)
  const boat = Object.values(bot.entities)
    .filter(entity => entity.id !== bot.entity.id)
    .find(entity => String(entity.name || '').toLowerCase().includes(spec.match))
  if (!boat) throw new Error(`${VEHICLE_KIND} did not spawn`)
  if (INTERMEDIATE_KIND) {
    const intermediate = VEHICLES[INTERMEDIATE_KIND]
    bot.chat(`/summon ${intermediate.selector} ${START_X} ${Y} ${Z} ${intermediate.nbt}`)
    await sleep(180)
    bot.chat(
      `/ride @e[type=${intermediate.selector},limit=1,sort=nearest]` +
      ` mount @e[type=${spec.selector},limit=1,sort=nearest]`
    )
    await sleep(180)
  }
  const mounted = onceWithTimeout(bot, 'mount', 2000)
  const mountSelector = INTERMEDIATE_KIND
    ? VEHICLES[INTERMEDIATE_KIND].selector
    : spec.selector
  bot.chat(`/ride @s mount @e[type=${mountSelector},limit=1,sort=nearest]`)
  await mounted
  await sleep(180)
  const initial = await snapshot(bot)
  if (!initial.ok || initial.vehicle === 'none') throw new Error('Server mount not authoritative')
  return boat
}

function writeVehicleMove (bot, boat, x, yOffset) {
  const y = Y + yOffset
  boat.position.set(x, y, Z)
  bot.entity.position.set(x, y, Z)
  bot._client.write('vehicle_move', {
    x,
    y,
    z: Z,
    yaw: -90,
    pitch: 0,
    onGround: yOffset === 0
  })
}

async function driveIntoWall (bot, boat, profile, correctionEvents) {
  let packets = 0
  for (let x = START_X + 0.25; x < TARGET_X - 1e-9; x += 0.25) {
    writeVehicleMove(bot, boat, x, profile.vehicleYOffset)
    packets++
    await sleep(TICK_MS)
  }
  writeVehicleMove(bot, boat, TARGET_X, profile.vehicleYOffset)
  packets++
  await sleep(350)
  return { packets, corrections: correctionEvents.length }
}

function overlapsWall (position) {
  const halfWidth = 0.30
  return position.x + halfWidth > WALL_MIN_X && position.x - halfWidth < WALL_MAX_X
}

async function escapeAsPlayer (bot, start, profile, correctionEvents) {
  let x = start.x + profile.playerStep
  let packets = 0
  const y = start.y + profile.playerYOffset
  while (x < TARGET_X - 1e-9 && correctionEvents.length === 0) {
    bot._client.write('position', {
      x,
      y,
      z: start.z,
      flags: { onGround: profile.onGround, hasHorizontalCollision: true }
    })
    bot.entity.position.set(x, y, start.z)
    packets++
    x += profile.playerStep
    await sleep(TICK_MS)
  }
  if (correctionEvents.length === 0) {
    bot._client.write('position', {
      x: TARGET_X,
      y,
      z: start.z,
      flags: { onGround: profile.onGround, hasHorizontalCollision: true }
    })
    bot.entity.position.set(TARGET_X, y, start.z)
    packets++
  }
  await sleep(500)
  return { packets, corrections: correctionEvents.length }
}

async function openWitness (bot) {
  const block = bot.blockAt(WITNESS)
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  }
  const opened = onceWithTimeout(bot, 'windowOpen', 1500)
  try {
    await bot.lookAt(WITNESS.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  if (!await opened) return { opened: false, reason: 'no_window' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function runTrial (bot, profile, index) {
  await reset(bot)
  const boat = await mountBoat(bot)
  const vehicleCorrections = []
  const playerCorrections = []
  const passengerEvents = []
  const vehicleHandler = packet => vehicleCorrections.push(packet)
  const playerHandler = packet => playerCorrections.push(packet)
  const passengerHandler = packet => passengerEvents.push(packet)
  bot._client.on('vehicle_move', vehicleHandler)
  bot._client.on('position', playerHandler)
  bot._client.on('set_passengers', passengerHandler)

  const drive = await driveIntoWall(bot, boat, profile, vehicleCorrections)
  const overlapSnapshot = await snapshot(bot)
  const overlap = overlapSnapshot.ok && overlapsWall(overlapSnapshot.position)
  const detached = overlapSnapshot.ok && overlapSnapshot.vehicle === 'none'

  // Corrections that happened during the vehicle leg are evidence, but only
  // fresh player corrections stop the fallback escape leg.
  playerCorrections.length = 0
  const escape = overlap && detached
    ? await escapeAsPlayer(bot, overlapSnapshot.position, profile, playerCorrections)
    : { packets: 0, corrections: 0 }

  const finalSnapshot = await snapshot(bot)
  const beyond = finalSnapshot.ok && finalSnapshot.position.x >= TARGET_X - 0.05
  const mountedBeyond = beyond && finalSnapshot.vehicle !== 'none'
  const exitBeyond = beyond && finalSnapshot.vehicle === 'none'
  const witness = beyond ? await openWitness(bot) : { opened: false, reason: 'not_beyond' }

  bot._client.removeListener('vehicle_move', vehicleHandler)
  bot._client.removeListener('position', playerHandler)
  bot._client.removeListener('set_passengers', passengerHandler)

  return {
    index,
    profile,
    drive,
    vehicleCorrections: vehicleCorrections.length,
    passengerEvents: passengerEvents.length,
    overlapSnapshot,
    overlap,
    detached,
    escape,
    finalSnapshot,
    beyond,
    mountedBeyond,
    exitBeyond,
    witness,
    mountedVerified: mountedBeyond && witness.opened,
    exitVerified: exitBeyond && witness.opened,
    verified: beyond && witness.opened
  }
}

function writeReport (results, bot) {
  const report = {
    metadata: {
      generatedAt: new Date().toISOString(),
      endpoint: `${HOST}:${PORT}`,
      vehicle: VEHICLE_KIND,
      intermediate: INTERMEDIATE_KIND || null,
      profileSet: PROFILE_SET,
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      wall: { minX: WALL_MIN_X, maxX: WALL_MAX_X, height: 6 },
      proof: 'server snapshot beyond wall plus far-side barrel opened'
    },
    results
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-overlap-escape-report.json'), JSON.stringify(report, null, 2))
  const rows = [
    'index,profile,vehicle_y_offset,player_step,player_y_offset,on_ground,vehicle_packets,vehicle_corrections,passenger_events,overlap,detached,overlap_x,overlap_y,player_packets,player_corrections,final_x,final_y,final_vehicle,beyond,mounted_beyond,exit_beyond,witness,mounted_verified,exit_verified,verified'
  ]
  for (const result of results) {
    rows.push([
      result.index,
      result.profile.id,
      result.profile.vehicleYOffset,
      result.profile.playerStep,
      result.profile.playerYOffset,
      result.profile.onGround,
      result.drive.packets,
      result.vehicleCorrections,
      result.passengerEvents,
      result.overlap,
      result.detached,
      result.overlapSnapshot.position?.x?.toFixed(6) ?? '',
      result.overlapSnapshot.position?.y?.toFixed(6) ?? '',
      result.escape.packets,
      result.escape.corrections,
      result.finalSnapshot.position?.x?.toFixed(6) ?? '',
      result.finalSnapshot.position?.y?.toFixed(6) ?? '',
      result.finalSnapshot.vehicle ?? '',
      result.beyond,
      result.mountedBeyond,
      result.exitBeyond,
      result.witness.opened,
      result.mountedVerified,
      result.exitVerified,
      result.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-overlap-escape-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab overlap probe complete')
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
    version: CLIENT_VERSION,
    physicsEnabled: false,
    hideErrors: false
  })
  bot.on('kicked', reason => console.error('[VehicleOverlap kicked]', reason))
  bot.on('error', error => console.error('[VehicleOverlap error]', error))

  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setup(bot)
    const results = []
    for (let index = 0; index < PROFILES.length; index++) {
      const result = await runTrial(bot, PROFILES[index], index)
      results.push(result)
      writeReport(results, bot)
      console.log(
        `[VehicleOverlap] ${index + 1}/${PROFILES.length} ${result.profile.id}` +
        ` overlap=${result.overlap} detached=${result.detached}` +
        ` overlapX=${result.overlapSnapshot.position?.x?.toFixed(3) ?? 'none'}` +
        ` finalX=${result.finalSnapshot.position?.x?.toFixed(3) ?? 'none'}` +
        ` witness=${result.witness.opened} VERIFIED=${result.verified}`
      )
    }
    console.log(`[VehicleOverlap] completed=${results.length} verified=${results.filter(r => r.verified).length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[VehicleOverlap fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
