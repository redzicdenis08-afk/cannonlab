'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-private-adaptive-horse-p4-directions')
const Y = 65
const STEP = 0.25
const PAUSE_MS = 350
const PACKET_INTERVAL_MS = 50
const THICKNESS = 64

const DIRECTIONS = {
  east: {
    dx: 1,
    dz: 0,
    yaw: -90,
    start: { x: 13.25, z: 8.5 },
    wall: { x1: 16, y1: 65, z1: 5, x2: 79, y2: 69, z2: 11 },
    chamber: { x: 83.5, z: 8.5 }
  },
  west: {
    dx: -1,
    dz: 0,
    yaw: 90,
    start: { x: 2.75, z: 8.5 },
    wall: { x1: -64, y1: 65, z1: 5, x2: -1, y2: 69, z2: 11 },
    chamber: { x: -67.5, z: 8.5 }
  },
  south: {
    dx: 0,
    dz: 1,
    yaw: 0,
    start: { x: 8.5, z: 13.25 },
    wall: { x1: 5, y1: 65, z1: 16, x2: 11, y2: 69, z2: 79 },
    chamber: { x: 8.5, z: 83.5 }
  },
  north: {
    dx: 0,
    dz: -1,
    yaw: 180,
    start: { x: 8.5, z: 2.75 },
    wall: { x1: 5, y1: 65, z1: -64, x2: 11, y2: 69, z2: -1 },
    chamber: { x: 8.5, z: -67.5 }
  }
}

const VEHICLES = {
  boat: {
    entityType: 'minecraft:oak_boat',
    serverType: 'OAK_BOAT',
    segmentLength: 2.0,
    labelPattern: 'boat'
  },
  horse: {
    entityType: 'minecraft:horse',
    serverType: 'HORSE',
    segmentLength: 4.0,
    labelPattern: 'horse'
  }
}

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  host: HOST,
  port: PORT,
  version: VERSION,
  scope: 'authorized exact private Sakura/Factions calibrated horse p4 all-cardinal matrix',
  claimsVerified: false,
  trials: [],
  fatal: null
}

function record (type, data = {}) {
  const row = { ts: new Date().toISOString(), type, ...data }
  transcript.push(row)
  process.stdout.write(`${JSON.stringify(row)}\n`)
}

function onceWithTimeout (emitter, eventName, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => finish(new Error(`Timeout waiting for ${eventName}`)), timeoutMs)
    const handler = (...args) => finish(null, args)
    function finish (error, value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      emitter.removeListener(eventName, handler)
      if (error) reject(error)
      else resolve(value)
    }
    emitter.once(eventName, handler)
  })
}

async function connect (username) {
  const bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username,
    auth: 'offline',
    version: VERSION,
    checkTimeoutInterval: 30000
  })
  bot.on('messagestr', message => record('chat', { username, message: String(message) }))
  bot.on('kicked', reason => record('kicked', { username, reason: String(reason) }))
  bot.on('error', error => record('bot_error', { username, error: String(error.stack || error) }))
  await onceWithTimeout(bot, 'spawn', 45000)
  record('spawn', { username, position: bot.entity.position })
  return bot
}

async function command (bot, text, delay = 350) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 6000) {
  record('command', { username: bot.username, text, expect: String(pattern) })
  return await new Promise((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => finish(new Error(`Timeout waiting for ${pattern} after ${text}`)), timeoutMs)
    const handler = message => {
      const rendered = String(message)
      if (pattern.test(rendered)) finish(null, rendered)
    }
    function finish (error, value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      bot.removeListener('messagestr', handler)
      if (error) reject(error)
      else resolve(value)
    }
    bot.on('messagestr', handler)
    bot.chat(text)
  })
}

function waitForToken (bot, token, timeoutMs = 3000) {
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

async function serverWitness (phaseBot, selector, label) {
  const token = `PHASELAB_${label}_${Date.now()}_${Math.random().toString(16).slice(2)}`
  const seen = waitForToken(phaseBot, token)
  phaseBot.chat(`/execute if entity ${selector} run tellraw PhaseBot {"text":"${token}"}`)
  return await seen
}

function selectorAroundPlayer (position, radius = 2.0) {
  return `@a[name=AttackerBot,x=${position.x - radius},y=63,z=${position.z - radius},dx=${radius * 2},dy=8,dz=${radius * 2},limit=1]`
}

function selectorAroundVehicle (vehicleType, position, radius = 2.5) {
  return `@e[type=${vehicleType},x=${position.x - radius},y=63,z=${position.z - radius},dx=${radius * 2},dy=8,dz=${radius * 2},limit=1]`
}

function parseJsonSuffix (message) {
  const index = message.indexOf('{')
  if (index < 0) throw new Error(`No JSON in message: ${message}`)
  return JSON.parse(message.slice(index))
}

async function setupFactions (phaseBot, victimBot, attackerBot) {
  await command(phaseBot, '/stacklab build', 650)
  await command(phaseBot, '/tp AttackerBot 8.5 65 8.5')
  await command(attackerBot, '/f create Attackers', 900)
  await command(phaseBot, '/fa power set AttackerBot 1000', 500)
  await command(attackerBot, '/f claim', 700)

  await command(phaseBot, '/tp VictimBot 24.5 65 8.5')
  await command(victimBot, '/f create Victims', 900)
  await command(phaseBot, '/fa power set VictimBot 10', 500)
  await commandExpect(
    phaseBot,
    '/stacklab factionboost Victims 1000',
    /STACKLAB FACTION BOOST .*"actual":1000.*"verified":true/,
    6000
  )

  const armChunks = []
  for (let i = 1; i <= 6; i++) {
    armChunks.push([i, 0], [-i, 0], [0, i], [0, -i])
  }
  for (const [chunkX, chunkZ] of armChunks) {
    await commandExpect(
      phaseBot,
      `/stacklab claimset Victims ${chunkX} ${chunkZ}`,
      /STACKLAB CLAIM SET .*"actual_tag":"Victims".*"verified":true/,
      6000
    )
  }

  const response = await commandExpect(
    phaseBot,
    '/stacklab directionclaimsnapshot direction-setup',
    /STACKLAB DIRECTION CLAIM WITNESS /,
    8000
  )
  const witness = parseJsonSuffix(response)
  const victimKeys = [
    'east_near_tag', 'east_far_tag',
    'west_near_tag', 'west_far_tag',
    'south_near_tag', 'south_far_tag',
    'north_near_tag', 'north_far_tag'
  ]
  const wildernessKeys = [
    'east_near_wilderness', 'east_far_wilderness',
    'west_near_wilderness', 'west_far_wilderness',
    'south_near_wilderness', 'south_far_wilderness',
    'north_near_wilderness', 'north_far_wilderness'
  ]
  const valid = witness.verified === true &&
    witness.center_tag === 'Attackers' &&
    witness.center_wilderness === false &&
    victimKeys.every(key => witness[key] === 'Victims') &&
    wildernessKeys.every(key => witness[key] === false)
  if (!valid) throw new Error(`Four-direction claim witness failed: ${JSON.stringify(witness)}`)
  report.claimsVerified = true
  report.claimWitness = witness
  record('claims_verified', { witness })
}

async function buildCourses (phaseBot) {
  await command(phaseBot, '/fill -90 63 4 90 72 12 minecraft:air', 800)
  await command(phaseBot, '/fill 4 63 -90 12 72 90 minecraft:air', 800)
  await command(phaseBot, '/fill -90 64 4 90 64 12 minecraft:stone', 500)
  await command(phaseBot, '/fill 4 64 -90 12 64 90 minecraft:stone', 500)

  for (const [name, direction] of Object.entries(DIRECTIONS)) {
    const wall = direction.wall
    await command(phaseBot, `/fill ${wall.x1} ${wall.y1} ${wall.z1} ${wall.x2} ${wall.y2} ${wall.z2} minecraft:obsidian`, 500)

    const cx = Math.floor(direction.chamber.x)
    const cz = Math.floor(direction.chamber.z)
    await command(phaseBot, `/fill ${cx - 3} 64 ${cz - 3} ${cx + 3} 69 ${cz + 3} minecraft:obsidian`, 250)
    await command(phaseBot, `/fill ${cx - 2} 65 ${cz - 2} ${cx + 2} 68 ${cz + 2} minecraft:air`, 200)
    record('course_built', { direction: name, wall, chamber: direction.chamber })
  }
}

function captureCorrections (bot, vehicleId) {
  const started = process.hrtime.bigint()
  const hardEvents = []
  const playerSyncs = []
  const wrap = (type, packet) => ({
    type,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    packet
  })
  const vehicleMove = packet => hardEvents.push(wrap('vehicle_move', packet))
  // A player-position packet while riding is not automatically a setback.
  // Server witnesses after each segment decide whether it retained progress.
  const playerPosition = packet => playerSyncs.push(wrap('player_position', packet))
  const teleport = packet => {
    if (packet.entityId === vehicleId) hardEvents.push(wrap('vehicle_entity_teleport', packet))
  }
  bot._client.on('vehicle_move', vehicleMove)
  bot._client.on('position', playerPosition)
  bot._client.on('entity_teleport', teleport)
  return {
    events: hardEvents,
    hardEvents,
    playerSyncs,
    stop () {
      bot._client.removeListener('vehicle_move', vehicleMove)
      bot._client.removeListener('position', playerPosition)
      bot._client.removeListener('entity_teleport', teleport)
    }
  }
}

async function waitForVehicleEntity (bot, labelPattern, timeoutMs = 7000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const entity = Object.values(bot.entities).find(candidate => {
      if (!candidate || !candidate.position) return false
      const label = `${candidate.name || ''} ${candidate.displayName || ''}`.toLowerCase()
      return label.includes(labelPattern) && candidate.position.distanceTo(bot.entity.position) < 8
    })
    if (entity) return entity
    await sleep(100)
  }
  return null
}

async function resetAttacker (phaseBot, attackerBot, direction) {
  try {
    await command(phaseBot, '/stacklab vehicledismount AttackerBot', 100)
  } catch {}
  attackerBot.vehicle = null
  attackerBot.entity.vehicle = null
  await command(phaseBot, '/kill @e[type=minecraft:oak_boat]', 100)
  await command(phaseBot, '/kill @e[type=minecraft:horse]', 100)
  await command(phaseBot, '/kill @e[type=minecraft:item]', 100)
  await command(phaseBot, '/clear AttackerBot', 100)
  await command(
    phaseBot,
    `/tp AttackerBot ${direction.start.x} ${Y} ${direction.start.z} ${direction.yaw} 45`,
    350
  )
}

async function prepareVehicle (phaseBot, attackerBot, vehicleName, direction) {
  const vehicle = VEHICLES[vehicleName]
  if (vehicleName === 'boat') {
    const response = await commandExpect(
      phaseBot,
      '/stacklab boatuse AttackerBot',
      /STACKLAB BOAT USE .*"accepted":true/,
      7000
    )
    record('boat_use', { direction: direction.name, response })
  } else {
    await command(phaseBot, `/tp AttackerBot ${direction.start.x} ${Y} ${direction.start.z} ${direction.yaw} 0`, 250)
    const response = await commandExpect(
      phaseBot,
      '/stacklab horseprep AttackerBot',
      /STACKLAB HORSE PREP .*"saddled":true.*"fire_resistance":true/,
      7000
    )
    record('horse_prep', { direction: direction.name, response })
  }

  const entity = await waitForVehicleEntity(attackerBot, vehicle.labelPattern)
  if (!entity) throw new Error(`${vehicleName} entity not visible near AttackerBot`)

  const mountedEvent = onceWithTimeout(attackerBot, 'mount', 1800).catch(() => null)
  const interaction = await commandExpect(
    phaseBot,
    `/stacklab vehicleinteract AttackerBot ${vehicle.serverType}`,
    new RegExp(`STACKLAB VEHICLE INTERACT .*"mounted":true.*"vehicle_type":"${vehicle.serverType}"`),
    7000
  )
  await mountedEvent
  await sleep(250)
  const check = await commandExpect(
    phaseBot,
    '/stacklab vehiclecheck AttackerBot',
    /STACKLAB VEHICLE CHECK /,
    5000
  )
  if (!check.includes('"mounted":true') || !check.includes(`"vehicle_type":"${vehicle.serverType}"`)) {
    throw new Error(`Server mount check failed vehicle=${vehicleName} check=${check}`)
  }

  if (!attackerBot.vehicle) {
    attackerBot.vehicle = entity
    attackerBot.entity.vehicle = entity
    if (!entity.passengers.includes(attackerBot.entity)) entity.passengers.push(attackerBot.entity)
    record('client_mount_state_repaired', { vehicle: vehicleName, entityId: entity.id })
  }
  record('vehicle_ready', {
    direction: direction.name,
    vehicle: vehicleName,
    entityId: attackerBot.vehicle.id,
    position: attackerBot.vehicle.position,
    interaction
  })
  return attackerBot.vehicle
}

async function sendRange (bot, start, direction, fromDistance, toDistance, fixedY, yaw, correctionRef) {
  let packets = 0
  let distance = fromDistance + STEP
  while (distance <= toDistance + 1.0E-9 && bot.vehicle && !correctionRef.value) {
    for (let group = 0; group < 4 && distance <= toDistance + 1.0E-9; group++) {
      const clamped = Math.min(distance, toDistance)
      const x = start.x + direction.dx * clamped
      const z = start.z + direction.dz * clamped
      bot.vehicle.position.set(x, fixedY, z)
      bot._client.write('vehicle_move', { x, y: fixedY, z, yaw, pitch: 0, onGround: true })
      packets++
      distance += STEP
      if (clamped >= toDistance - 1.0E-9) break
    }
    await sleep(PACKET_INTERVAL_MS)
  }
  return packets
}

async function sendRatchet (phaseBot, attackerBot, trial, start, fixedY, targetDistance, correctionRef) {
  let acceptedDistance = 0
  let packets = 0
  let segment = 0
  const witnesses = []

  while (acceptedDistance < targetDistance - 1.0E-9 && attackerBot.vehicle && !correctionRef.value) {
    segment++
    const segmentTarget = Math.min(targetDistance, acceptedDistance + trial.segmentLength)
    packets += await sendRange(
      attackerBot,
      start,
      trial.direction,
      acceptedDistance,
      segmentTarget,
      fixedY,
      trial.direction.yaw,
      correctionRef
    )
    await sleep(PAUSE_MS)

    const expected = {
      x: start.x + trial.direction.dx * segmentTarget,
      z: start.z + trial.direction.dz * segmentTarget
    }
    const playerAccepted = await serverWitness(
      phaseBot,
      selectorAroundPlayer(expected, 2.0),
      `ADAPT_PLAYER_${trial.id}_${segment}`
    )
    const vehicleAccepted = await serverWitness(
      phaseBot,
      selectorAroundVehicle(trial.vehicle.entityType, expected, 2.5),
      `ADAPT_VEHICLE_${trial.id}_${segment}`
    )
    const witness = {
      segment,
      fromDistance: acceptedDistance,
      targetDistance: segmentTarget,
      expected,
      playerAccepted,
      vehicleAccepted,
      correctionsSoFar: correctionRef.value
    }
    witnesses.push(witness)
    record('adaptive_segment_witness', { trial: trial.id, ...witness })
    if (!playerAccepted || !vehicleAccepted || correctionRef.value) break
    acceptedDistance = segmentTarget
  }

  return { packets, witnesses, acceptedDistance }
}

async function runTrial (phaseBot, attackerBot, vehicleName, directionName, run) {
  const direction = { name: directionName, ...DIRECTIONS[directionName] }
  const vehicle = VEHICLES[vehicleName]
  const id = `${vehicleName}-${directionName}-solid${THICKNESS}`
  const trial = { id, vehicle, direction, segmentLength: vehicle.segmentLength }

  await resetAttacker(phaseBot, attackerBot, direction)
  await command(
    phaseBot,
    `/summon minecraft:item ${direction.chamber.x} ${Y} ${direction.chamber.z} {Item:{id:"minecraft:netherite_block",count:1}}`,
    150
  )
  const mountedVehicle = await prepareVehicle(phaseBot, attackerBot, vehicleName, direction)
  const start = { x: mountedVehicle.position.x, z: mountedVehicle.position.z }
  const fixedY = mountedVehicle.position.y
  const targetDistance =
    (direction.chamber.x - start.x) * direction.dx +
    (direction.chamber.z - start.z) * direction.dz
  if (!(targetDistance > THICKNESS)) {
    throw new Error(`Invalid target distance ${targetDistance} for ${id}`)
  }

  const corrections = captureCorrections(attackerBot, mountedVehicle.id)
  const correctionRef = { value: false }
  const watcher = setInterval(() => {
    correctionRef.value = corrections.events.length > 0
  }, 1)

  const started = Date.now()
  const sequence = await sendRatchet(
    phaseBot,
    attackerBot,
    trial,
    start,
    fixedY,
    targetDistance,
    correctionRef
  )
  await sleep(350)
  clearInterval(watcher)

  const playerMounted = await serverWitness(
    phaseBot,
    selectorAroundPlayer(direction.chamber, 3.0),
    `FINAL_PLAYER_MOUNTED_${id}_${run}`
  )
  const vehicleBeyond = await serverWitness(
    phaseBot,
    selectorAroundVehicle(vehicle.entityType, direction.chamber, 3.5),
    `FINAL_VEHICLE_${id}_${run}`
  )
  const movementCorrectionCount = corrections.events.length
  const firstMovementCorrection = corrections.events[0] || null

  let dismountResponse = null
  let dismountError = null
  try {
    dismountResponse = await commandExpect(
      phaseBot,
      '/stacklab vehicledismount AttackerBot',
      /STACKLAB VEHICLE DISMOUNT .*"mounted":false/,
      6000
    )
    attackerBot.vehicle = null
    attackerBot.entity.vehicle = null
  } catch (error) {
    dismountError = String(error.stack || error)
  }
  await sleep(900)

  const playerDismounted = await serverWitness(
    phaseBot,
    selectorAroundPlayer(direction.chamber, 4.0),
    `FINAL_PLAYER_DISMOUNTED_${id}_${run}`
  )
  const netheriteCount = attackerBot.inventory.items()
    .filter(item => item.name === 'netherite_block')
    .reduce((sum, item) => sum + item.count, 0)

  corrections.stop()
  const allSegmentsAccepted = sequence.witnesses.length > 0 && sequence.witnesses.every(row => row.playerAccepted && row.vehicleAccepted)
  const result = {
    id,
    run,
    direction: directionName,
    vehicle: vehicleName,
    thickness: THICKNESS,
    start,
    fixedY,
    target: direction.chamber,
    targetDistance,
    segmentLength: vehicle.segmentLength,
    packetsPerTick: 4,
    pauseMs: PAUSE_MS,
    step: STEP,
    elapsedMs: Date.now() - started,
    packetCount: sequence.packets,
    segmentCount: sequence.witnesses.length,
    acceptedDistance: sequence.acceptedDistance,
    allSegmentsAccepted,
    playerMounted,
    vehicleBeyond,
    playerDismounted,
    netheriteCount,
    movementCorrectionCount,
    firstMovementCorrection,
    playerSyncCount: corrections.playerSyncs.length,
    firstPlayerSync: corrections.playerSyncs[0] || null,
    dismountResponse,
    dismountError,
    clientPlayerPosition: attackerBot.entity.position
  }
  result.serverAuthoritativeSuccess = Boolean(
    allSegmentsAccepted &&
    playerMounted &&
    vehicleBeyond &&
    playerDismounted &&
    netheriteCount >= 1 &&
    movementCorrectionCount === 0
  )
  report.trials.push(result)
  record('adaptive_horse_p4_direction_trial', result)
  return result
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const victimBot = await connect('VictimBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, victimBot, attackerBot]

  try {
    await command(phaseBot, '/gamerule doDaylightCycle false')
    await command(phaseBot, '/gamerule doFireTick false')
    await command(phaseBot, '/time set day')
    await command(phaseBot, '/difficulty peaceful')
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival VictimBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    await command(phaseBot, '/effect give AttackerBot minecraft:resistance infinite 255 true')
    await setupFactions(phaseBot, victimBot, attackerBot)
    await buildCourses(phaseBot)

    for (const vehicleName of ['horse']) {
      for (const directionName of Object.keys(DIRECTIONS)) {
        for (let run = 1; run <= 1; run++) {
          try {
            await runTrial(phaseBot, attackerBot, vehicleName, directionName, run)
          } catch (error) {
            const failure = {
              id: `${vehicleName}-${directionName}-solid${THICKNESS}`,
              run,
              direction: directionName,
              vehicle: vehicleName,
              serverAuthoritativeSuccess: false,
              error: String(error.stack || error)
            }
            report.trials.push(failure)
            record('adaptive_horse_p4_direction_trial_error', failure)
          }
        }
      }
    }
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    report.successCount = report.trials.filter(row => row.serverAuthoritativeSuccess).length
    report.totalCount = report.trials.length
    report.byFamily = Object.fromEntries(
      [...new Set(report.trials.map(row => row.id))].map(id => {
        const rows = report.trials.filter(row => row.id === id)
        return [id, {
          successes: rows.filter(row => row.serverAuthoritativeSuccess).length,
          attempts: rows.length
        }]
      })
    )
    report.byVehicle = Object.fromEntries(
      Object.keys(VEHICLES).map(vehicleName => {
        const rows = report.trials.filter(row => row.vehicle === vehicleName)
        return [vehicleName, {
          successes: rows.filter(row => row.serverAuthoritativeSuccess).length,
          attempts: rows.length
        }]
      })
    )
    report.byDirection = Object.fromEntries(
      Object.keys(DIRECTIONS).map(directionName => {
        const rows = report.trials.filter(row => row.direction === directionName)
        return [directionName, {
          successes: rows.filter(row => row.serverAuthoritativeSuccess).length,
          attempts: rows.length
        }]
      })
    )

    fs.writeFileSync(
      path.join(OUTPUT_DIR, 'private-stack-adaptive-horse-p4-directions-report.json'),
      JSON.stringify(report, null, 2)
    )
    fs.writeFileSync(
      path.join(OUTPUT_DIR, 'private-stack-adaptive-horse-p4-directions-transcript.jsonl'),
      transcript.map(row => JSON.stringify(row)).join('\n') + '\n'
    )
    for (const bot of bots) {
      try { bot.quit('PhaseLab adaptive horse p4 directions matrix complete') } catch {}
    }
  }

  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(
    path.join(OUTPUT_DIR, 'private-stack-adaptive-horse-p4-directions-report.json'),
    JSON.stringify(report, null, 2)
  )
  process.exitCode = 1
})
