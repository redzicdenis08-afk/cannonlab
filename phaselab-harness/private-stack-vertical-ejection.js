'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-private-vertical')
const STEP = 0.25
const TOP_Y = 128.0
const TARGET_Y = 59.5
const PALETTE = ['minecraft:obsidian', 'minecraft:water']

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  scope: 'authorized exact private Sakura/Factions vertical vehicle phase matrix',
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

async function command (bot, text, delay = 300) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 7000) {
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

function vehicleSelectorType (vehicle) {
  return vehicle === 'horse' ? 'minecraft:horse' : 'minecraft:oak_boat'
}

function serverVehicleType (vehicle) {
  return vehicle === 'horse' ? 'HORSE' : 'OAK_BOAT'
}

function entityMatches (entity, vehicle) {
  if (!entity || !entity.position) return false
  const label = `${entity.name || ''} ${entity.displayName || ''}`.toLowerCase()
  return vehicle === 'horse' ? label.includes('horse') : label.includes('boat')
}

async function waitForVehicle (bot, vehicle, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const found = Object.values(bot.entities).find(entity => entityMatches(entity, vehicle) && entity.position.distanceTo(bot.entity.position) < 12)
    if (found) return found
    await sleep(100)
  }
  return null
}

async function setupFactions (phaseBot, victimBot, attackerBot) {
  await command(phaseBot, '/stacklab build', 600)
  await command(phaseBot, '/tp AttackerBot 24.5 65 0.5')
  await command(attackerBot, '/f create Attackers', 900)
  await command(phaseBot, '/fa power set AttackerBot 10', 300)
  await commandExpect(phaseBot, '/stacklab factionboost Attackers 100', /STACKLAB FACTION BOOST .*"verified":true/, 6000)
  await commandExpect(phaseBot, '/stacklab claimset Attackers 1 0', /STACKLAB CLAIM SET .*"actual_tag":"Attackers".*"verified":true/, 6000)

  await command(phaseBot, '/tp VictimBot 40.5 65 0.5')
  await command(victimBot, '/f create Victims', 900)
  await command(phaseBot, '/fa power set VictimBot 10', 300)
  await commandExpect(phaseBot, '/stacklab factionboost Victims 100', /STACKLAB FACTION BOOST .*"verified":true/, 6000)
  const witness = await commandExpect(
    phaseBot,
    '/stacklab claimset Victims 0 0',
    /STACKLAB CLAIM SET .*"actual_tag":"Victims".*"verified":true/,
    6000
  )
  report.claimsVerified = true
  report.claimWitness = witness
  record('claims_verified', { witness })
}

async function buildVerticalCourse (phaseBot) {
  await command(phaseBot, '/fill -8 54 -8 8 138 8 minecraft:air', 1000)
  await command(phaseBot, '/fill -7 54 -7 7 64 7 minecraft:obsidian', 300)
  await command(phaseBot, '/fill -5 56 -5 5 63 5 minecraft:air', 250)
  for (let y = 64; y <= 127; y++) {
    const material = PALETTE[(127 - y) % PALETTE.length]
    await command(phaseBot, `/fill -5 ${y} -5 5 ${y} 5 ${material}`, 25)
  }
  await command(phaseBot, `/summon minecraft:item 0.5 58.5 0.5 {Item:{id:"minecraft:netherite_block",count:1}}`, 150)
  record('course_built', {
    topY: TOP_Y,
    targetY: TARGET_Y,
    layers: 64,
    palette: PALETTE
  })
}

async function resetAttacker (phaseBot, attackerBot, vehicle) {
  try { await command(phaseBot, '/stacklab vehicledismount AttackerBot', 100) } catch {}
  attackerBot.vehicle = null
  attackerBot.entity.vehicle = null
  await command(phaseBot, '/kill @e[type=minecraft:oak_boat]', 100)
  await command(phaseBot, '/kill @e[type=minecraft:horse]', 100)
  await command(phaseBot, '/kill @e[type=minecraft:item]', 100)
  await command(phaseBot, '/clear AttackerBot', 100)
  if (vehicle === 'boat') {
    await command(phaseBot, '/tp AttackerBot 0.5 130 4.5 180 45', 350)
  } else {
    await command(phaseBot, '/tp AttackerBot 0.5 130 4.0 180 0', 350)
  }
}

async function prepareVehicle (phaseBot, attackerBot, vehicle) {
  if (vehicle === 'boat') {
    await commandExpect(
      phaseBot,
      '/stacklab boatuse AttackerBot',
      /STACKLAB BOAT USE .*"accepted":true/,
      9000
    )
  } else {
    await commandExpect(
      phaseBot,
      '/stacklab horseprep AttackerBot',
      /STACKLAB HORSE PREP .*"saddled":true.*"fire_resistance":true/,
      7000
    )
  }
  const entity = await waitForVehicle(attackerBot, vehicle)
  if (!entity) throw new Error(`No visible ${vehicle} after preparation`)
  await commandExpect(
    phaseBot,
    `/stacklab vehicleinteract AttackerBot ${serverVehicleType(vehicle)}`,
    new RegExp(`STACKLAB VEHICLE INTERACT .*"mounted":true.*"vehicle_type":"${serverVehicleType(vehicle)}"`),
    7000
  )
  await sleep(300)
  const check = await commandExpect(phaseBot, '/stacklab vehiclecheck AttackerBot', /STACKLAB VEHICLE CHECK /, 5000)
  if (!check.includes('"mounted":true') || !check.includes(`"vehicle_type":"${serverVehicleType(vehicle)}"`)) {
    throw new Error(`Mount check failed: ${check}`)
  }
  if (!attackerBot.vehicle) {
    attackerBot.vehicle = entity
    attackerBot.entity.vehicle = entity
    if (!entity.passengers.includes(attackerBot.entity)) entity.passengers.push(attackerBot.entity)
  }
  return attackerBot.vehicle
}

async function realPulse (phaseBot, attackerBot, vehicle, existingEntity) {
  const dismount = await commandExpect(
    phaseBot,
    '/stacklab vehicledismount AttackerBot',
    /STACKLAB VEHICLE DISMOUNT .*"mounted":false/,
    6000
  )
  attackerBot.vehicle = null
  attackerBot.entity.vehicle = null
  await sleep(150)
  const remount = await commandExpect(
    phaseBot,
    `/stacklab vehicleinteract AttackerBot ${serverVehicleType(vehicle)}`,
    new RegExp(`STACKLAB VEHICLE INTERACT .*"mounted":true.*"vehicle_type":"${serverVehicleType(vehicle)}"`),
    7000
  )
  await sleep(180)
  const visible = Object.values(attackerBot.entities).find(entity => entity.id === existingEntity.id) || await waitForVehicle(attackerBot, vehicle, 2000)
  if (!visible) throw new Error(`Vehicle vanished during ${vehicle} pulse`)
  attackerBot.vehicle = visible
  attackerBot.entity.vehicle = visible
  if (!visible.passengers.includes(attackerBot.entity)) visible.passengers.push(attackerBot.entity)
  return { dismount, remount }
}

function captureCorrections (bot, vehicleId) {
  const events = []
  const vehicleMove = packet => events.push({ type: 'vehicle_move', packet, at: Date.now() })
  const teleport = packet => {
    if (packet.entityId === vehicleId) events.push({ type: 'vehicle_entity_teleport', packet, at: Date.now() })
  }
  bot._client.on('vehicle_move', vehicleMove)
  bot._client.on('entity_teleport', teleport)
  return {
    events,
    stop () {
      bot._client.removeListener('vehicle_move', vehicleMove)
      bot._client.removeListener('entity_teleport', teleport)
    }
  }
}

async function sendDownSegment (bot, targetY, onGround) {
  const vehicle = bot.vehicle
  if (!vehicle) throw new Error('No controlled vehicle for down segment')
  const x = vehicle.position.x
  const z = vehicle.position.z
  let packets = 0
  for (let y = vehicle.position.y - STEP; y > targetY + 1e-9; y -= STEP) {
    vehicle.position.set(x, y, z)
    bot.entity.position.set(x, y, z)
    bot._client.write('vehicle_move', { x, y, z, yaw: vehicle.yaw || 0, pitch: 90, onGround })
    packets++
    if (packets % 30 === 0) await new Promise(resolve => setImmediate(resolve))
  }
  vehicle.position.set(x, targetY, z)
  bot.entity.position.set(x, targetY, z)
  bot._client.write('vehicle_move', { x, y: targetY, z, yaw: vehicle.yaw || 0, pitch: 90, onGround })
  return packets + 1
}

function verticalPlayerSelector (x, y, z, radius = 2.5) {
  return `@a[name=AttackerBot,x=${x - radius},y=${y - radius},z=${z - radius},dx=${radius * 2},dy=${radius * 2},dz=${radius * 2},limit=1]`
}

function verticalVehicleSelector (vehicle, x, y, z, radius = 3.0) {
  return `@e[type=${vehicleSelectorType(vehicle)},x=${x - radius},y=${y - radius},z=${z - radius},dx=${radius * 2},dy=${radius * 2},dz=${radius * 2},limit=1]`
}


async function sendPlayerDownSegment (bot, startY, targetY, trial) {
  const x = bot.entity.position.x
  const z = bot.entity.position.z
  let packets = 0
  for (let y = startY - STEP; y > targetY + 1e-9; y -= STEP) {
    bot._client.write('position', {
      x,
      y,
      z,
      flags: { onGround: trial.onGround, hasHorizontalCollision: trial.horizontalCollision }
    })
    bot.entity.position.set(x, y, z)
    packets++
    if (trial.packetDelayMs > 0) await sleep(trial.packetDelayMs)
    else if (packets % 30 === 0) await new Promise(resolve => setImmediate(resolve))
  }
  bot._client.write('position', {
    x,
    y: targetY,
    z,
    flags: { onGround: trial.onGround, hasHorizontalCollision: trial.horizontalCollision }
  })
  bot.entity.position.set(x, targetY, z)
  return packets + 1
}

function captureAllCorrections (bot, vehicleId) {
  const events = []
  const playerPosition = packet => events.push({ type: 'player_position', packet, at: Date.now() })
  const vehicleMove = packet => events.push({ type: 'vehicle_move', packet, at: Date.now() })
  const teleport = packet => {
    if (packet.entityId === vehicleId) events.push({ type: 'vehicle_entity_teleport', packet, at: Date.now() })
  }
  bot._client.on('position', playerPosition)
  bot._client.on('vehicle_move', vehicleMove)
  bot._client.on('entity_teleport', teleport)
  return {
    events,
    stop () {
      bot._client.removeListener('position', playerPosition)
      bot._client.removeListener('vehicle_move', vehicleMove)
      bot._client.removeListener('entity_teleport', teleport)
    }
  }
}

function classifyStageEvents (events, expected) {
  const expectedRelocations = []
  const setbacks = []
  for (const event of events) {
    if (event.type === 'player_position') {
      const packet = event.packet || {}
      const close = Number.isFinite(packet.x) && Number.isFinite(packet.y) && Number.isFinite(packet.z)
        && Math.abs(packet.x - expected.x) <= 3.0
        && Math.abs(packet.y - expected.y) <= 1.0
        && Math.abs(packet.z - expected.z) <= 3.0
      if (close) expectedRelocations.push(event)
      else setbacks.push(event)
    } else {
      setbacks.push(event)
    }
  }
  return { expectedRelocations, setbacks }
}

async function remountExistingVehicle (phaseBot, attackerBot, trial, entity, acceptedY) {
  const response = await commandExpect(
    phaseBot,
    `/stacklab vehicleinteract AttackerBot ${serverVehicleType(trial.vehicle)}`,
    new RegExp(`STACKLAB VEHICLE INTERACT .*"mounted":true.*"vehicle_type":"${serverVehicleType(trial.vehicle)}"`),
    7000
  )
  await sleep(180)
  const visible = Object.values(attackerBot.entities).find(candidate => candidate.id === entity.id) || await waitForVehicle(attackerBot, trial.vehicle, 2000)
  if (!visible) throw new Error('Vehicle not visible after remount')
  attackerBot.vehicle = visible
  attackerBot.entity.vehicle = visible
  if (!visible.passengers.includes(attackerBot.entity)) visible.passengers.push(attackerBot.entity)

  const serverPlayerAtLowerAnchor = await serverWitness(
    phaseBot,
    verticalPlayerSelector(attackerBot.entity.position.x, acceptedY, attackerBot.entity.position.z, 3.5),
    `REMOUNT_PLAYER_LOWER_${trial.id}_${Date.now()}`
  )
  const serverVehicleAtLowerAnchor = await serverWitness(
    phaseBot,
    verticalVehicleSelector(trial.vehicle, attackerBot.entity.position.x, acceptedY, attackerBot.entity.position.z, 3.5),
    `REMOUNT_VEHICLE_LOWER_${trial.id}_${Date.now()}`
  )

  // Preserve the lower client anchor the real user observed after ejection.
  visible.position.set(attackerBot.entity.position.x, acceptedY, attackerBot.entity.position.z)
  attackerBot.entity.position.set(attackerBot.entity.position.x, acceptedY, attackerBot.entity.position.z)
  return { response, serverPlayerAtLowerAnchor, serverVehicleAtLowerAnchor }
}

async function runEjectionTrial (phaseBot, attackerBot, trial, run) {
  await buildVerticalCourse(phaseBot)
  await resetAttacker(phaseBot, attackerBot, trial.vehicle)
  if (trial.vehicle === 'horse') {
    await command(phaseBot, '/tp AttackerBot 0.5 128.25 4.0 180 0', 350)
  }
  const mountedVehicle = await prepareVehicle(phaseBot, attackerBot, trial.vehicle)
  const start = { x: mountedVehicle.position.x, y: mountedVehicle.position.y, z: mountedVehicle.position.z }
  await command(phaseBot, `/summon minecraft:item ${start.x} 58.5 ${start.z} {Item:{id:"minecraft:netherite_block",count:1}}`, 100)

  const telemetry = captureAllCorrections(attackerBot, mountedVehicle.id)
  const started = Date.now()
  let packetCount = 0
  const checkpoints = []
  const remounts = []

  // The proven primitive: one four-block vehicle burst ejects the player downward.
  const firstEventIndex = telemetry.events.length
  packetCount += await sendDownSegment(attackerBot, start.y - 4.0, false)
  await sleep(250)
  const firstY = start.y - 4.0
  const firstPlayerAccepted = await serverWitness(phaseBot, verticalPlayerSelector(start.x, firstY, start.z, 3.0), `EJECT_PLAYER_${trial.id}_${run}`)
  const firstVehicleStayed = await serverWitness(phaseBot, verticalVehicleSelector(trial.vehicle, start.x, start.y, start.z, 3.0), `EJECT_VEHICLE_TOP_${trial.id}_${run}`)
  const firstVehicleLower = await serverWitness(phaseBot, verticalVehicleSelector(trial.vehicle, start.x, firstY, start.z, 3.0), `EJECT_VEHICLE_LOWER_${trial.id}_${run}`)
  const firstClassification = classifyStageEvents(
    telemetry.events.slice(firstEventIndex),
    { x: start.x, y: firstY, z: start.z }
  )
  const setbacks = [...firstClassification.setbacks]
  const expectedRelocations = [...firstClassification.expectedRelocations]
  checkpoints.push({
    stage: 'first_eject',
    targetY: firstY,
    playerAccepted: firstPlayerAccepted,
    vehicleStayedTop: firstVehicleStayed,
    vehicleLower: firstVehicleLower,
    expectedRelocations: firstClassification.expectedRelocations.length,
    setbacks: firstClassification.setbacks.length
  })
  attackerBot.vehicle = null
  attackerBot.entity.vehicle = null

  let acceptedY = firstPlayerAccepted ? firstY : start.y
  if (firstPlayerAccepted && trial.chain === 'player') {
    while (acceptedY > TARGET_Y + 1e-9 && setbacks.length === 0) {
      const targetY = Math.max(TARGET_Y, acceptedY - trial.segmentLength)
      const stageEventIndex = telemetry.events.length
      packetCount += await sendPlayerDownSegment(attackerBot, acceptedY, targetY, trial)
      await sleep(trial.pauseMs)
      const accepted = await serverWitness(phaseBot, verticalPlayerSelector(start.x, targetY, start.z, 3.0), `PLAYER_CHAIN_${trial.id}_${run}_${targetY}`)
      const classification = classifyStageEvents(
        telemetry.events.slice(stageEventIndex),
        { x: start.x, y: targetY, z: start.z }
      )
      expectedRelocations.push(...classification.expectedRelocations)
      setbacks.push(...classification.setbacks)
      checkpoints.push({
        stage: 'player_chain',
        fromY: acceptedY,
        targetY,
        accepted,
        expectedRelocations: classification.expectedRelocations.length,
        setbacks: classification.setbacks.length
      })
      if (!accepted || classification.setbacks.length > 0) break
      acceptedY = targetY
    }
  } else if (firstPlayerAccepted && trial.chain === 'remount') {
    while (acceptedY > TARGET_Y + 1e-9 && setbacks.length === 0) {
      let remount
      try {
        remount = await remountExistingVehicle(phaseBot, attackerBot, trial, mountedVehicle, acceptedY)
        remounts.push(remount)
      } catch (error) {
        remounts.push({ error: String(error.stack || error) })
        break
      }
      const targetY = Math.max(TARGET_Y, acceptedY - trial.segmentLength)
      const stageEventIndex = telemetry.events.length
      packetCount += await sendDownSegment(attackerBot, targetY, false)
      await sleep(trial.pauseMs)
      const playerAccepted = await serverWitness(phaseBot, verticalPlayerSelector(start.x, targetY, start.z, 3.0), `REMOUNT_CHAIN_PLAYER_${trial.id}_${run}_${targetY}`)
      const vehicleAtTarget = await serverWitness(phaseBot, verticalVehicleSelector(trial.vehicle, start.x, targetY, start.z, 3.0), `REMOUNT_CHAIN_VEHICLE_${trial.id}_${run}_${targetY}`)
      const classification = classifyStageEvents(
        telemetry.events.slice(stageEventIndex),
        { x: start.x, y: targetY, z: start.z }
      )
      expectedRelocations.push(...classification.expectedRelocations)
      setbacks.push(...classification.setbacks)
      checkpoints.push({
        stage: 'remount_chain',
        fromY: acceptedY,
        targetY,
        playerAccepted,
        vehicleAtTarget,
        expectedRelocations: classification.expectedRelocations.length,
        setbacks: classification.setbacks.length
      })
      attackerBot.vehicle = null
      attackerBot.entity.vehicle = null
      if (!playerAccepted || classification.setbacks.length > 0) break
      acceptedY = targetY
    }
  }

  telemetry.stop()
  await sleep(700)
  const playerBelow = await serverWitness(phaseBot, verticalPlayerSelector(start.x, TARGET_Y, start.z, 6.0), `CHAIN_FINAL_PLAYER_${trial.id}_${run}`)
  const netheriteCount = attackerBot.inventory.items().filter(item => item.name === 'netherite_block').reduce((sum, item) => sum + item.count, 0)

  const result = {
    id: trial.id,
    run,
    vehicle: trial.vehicle,
    chain: trial.chain,
    onGround: trial.onGround,
    horizontalCollision: trial.horizontalCollision,
    packetDelayMs: trial.packetDelayMs,
    segmentLength: trial.segmentLength,
    pauseMs: trial.pauseMs,
    start,
    firstY,
    acceptedY,
    packetCount,
    checkpoints,
    remounts,
    telemetryCount: telemetry.events.length,
    expectedRelocationCount: expectedRelocations.length,
    setbackCount: setbacks.length,
    firstSetback: setbacks[0] || null,
    playerBelow,
    netheriteCount,
    elapsedMs: Date.now() - started
  }
  result.serverAuthoritativeSuccess = Boolean(
    acceptedY <= TARGET_Y + 1e-9 && playerBelow && netheriteCount >= 1 && setbacks.length === 0
  )
  report.trials.push(result)
  record('vertical_ejection_trial', result)
  return result
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const victimBot = await connect('VictimBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, victimBot, attackerBot]

  report.scope = 'authorized exact private Sakura/Factions no-lava vertical remount chain matrix'
  const trialPlan = [
    { id: 'boat-remount-anchor4-nolava', vehicle: 'boat', chain: 'remount', onGround: false, horizontalCollision: true, packetDelayMs: 0, segmentLength: 4, pauseMs: 120, repeats: 3 },
    { id: 'boat-player-air-hcoll-fast-nolava', vehicle: 'boat', chain: 'player', onGround: false, horizontalCollision: true, packetDelayMs: 0, segmentLength: 4, pauseMs: 100, repeats: 2 }
  ]

  try {
    await command(phaseBot, '/gamerule doDaylightCycle false')
    await command(phaseBot, '/gamerule doFireTick false')
    await command(phaseBot, '/time set day')
    await command(phaseBot, '/difficulty peaceful')
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival VictimBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    await command(phaseBot, '/effect give AttackerBot minecraft:resistance infinite 255 true')
    await command(phaseBot, '/effect give AttackerBot minecraft:fire_resistance infinite 0 true')
    await setupFactions(phaseBot, victimBot, attackerBot)

    for (const trial of trialPlan) {
      for (let run = 1; run <= trial.repeats; run++) {
        try {
          await runEjectionTrial(phaseBot, attackerBot, trial, run)
        } catch (error) {
          const failure = { ...trial, run, serverAuthoritativeSuccess: false, error: String(error.stack || error) }
          report.trials.push(failure)
          record('vertical_ejection_trial_error', failure)
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
    report.byFamily = Object.fromEntries([...new Set(report.trials.map(row => row.id))].map(id => {
      const rows = report.trials.filter(row => row.id === id)
      return [id, { successes: rows.filter(row => row.serverAuthoritativeSuccess).length, attempts: rows.length }]
    }))
    report.byVehicle = Object.fromEntries(['boat', 'horse'].map(vehicle => {
      const rows = report.trials.filter(row => row.vehicle === vehicle)
      return [vehicle, { successes: rows.filter(row => row.serverAuthoritativeSuccess).length, attempts: rows.length }]
    }))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-vertical-ejection-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-vertical-ejection-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab vertical ejection matrix complete') } catch {}
    }
  }

  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-vertical-ejection-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
