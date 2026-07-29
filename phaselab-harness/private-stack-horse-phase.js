'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-private-horse')
const Y = 65
const Z = 0.5
const WALL_START = 16
const BOAT_START = 15.15

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  host: HOST,
  port: PORT,
  version: VERSION,
  scope: 'authorized exact private Sakura/Factions stack horse vehicle phase',
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

function waitForToken (bot, token, timeoutMs = 2500) {
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

function captureCorrections (bot, boatId) {
  const started = process.hrtime.bigint()
  const events = []
  const add = (type, packet) => events.push({
    type,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    packet
  })
  const vehicleMove = packet => add('vehicle_move', packet)
  const playerPosition = packet => add('player_position', packet)
  const teleport = packet => {
    if (packet.entityId === boatId) add('boat_entity_teleport', packet)
  }
  bot._client.on('vehicle_move', vehicleMove)
  bot._client.on('position', playerPosition)
  bot._client.on('entity_teleport', teleport)
  return {
    events,
    stop () {
      bot._client.removeListener('vehicle_move', vehicleMove)
      bot._client.removeListener('position', playerPosition)
      bot._client.removeListener('entity_teleport', teleport)
    }
  }
}

async function setupFactions (phaseBot, victimBot, attackerBot) {
  await command(phaseBot, '/stacklab build', 650)
  await command(phaseBot, '/tp AttackerBot 8.5 65 0.5')
  await command(attackerBot, '/f create Attackers', 900)
  await command(phaseBot, '/fa power set AttackerBot 1000', 500)
  await command(attackerBot, '/f claim', 800)

  await command(phaseBot, '/tp VictimBot 24.5 65 0.5')
  await command(victimBot, '/f create Victims', 900)
  await command(phaseBot, '/fa power set VictimBot 1000', 500)
  for (let chunkX = 1; chunkX <= 16; chunkX++) {
    await command(phaseBot, `/tp VictimBot ${chunkX * 16 + 8}.5 65 0.5`, 150)
    await command(victimBot, '/f claim', 300)
  }

  await command(phaseBot, '/tp AttackerBot 14.5 65 0.5')
  const witness = await commandExpect(
    phaseBot,
    '/stacklab claimsnapshot vehicle-setup',
    /STACKLAB CLAIM WITNESS .*"attacker_tag":"Attackers".*"victim_tag":"Victims".*"verified":true/,
    7000
  )
  report.claimsVerified = true
  record('claims_verified', { witness })
}

async function buildCourse (phaseBot, trial) {
  const wallEnd = WALL_START + trial.thickness - 1
  const chamberX = wallEnd + 3
  const clearEnd = Math.max(chamberX + 10, 270)
  await command(phaseBot, `/fill 10 63 -4 ${clearEnd} 71 4 minecraft:air`, 600)
  await command(phaseBot, `/fill 10 64 -4 ${clearEnd} 64 4 minecraft:stone`, 500)

  if (trial.kind === 'solid') {
    await command(phaseBot, `/fill ${WALL_START} 65 -3 ${wallEnd} 69 3 minecraft:obsidian`, Math.min(2000, 300 + trial.thickness * 4))
  } else if (trial.kind === 'layered') {
    for (let x = WALL_START; x <= wallEnd; x++) {
      const material = ((x - WALL_START) % 2 === 0) ? 'minecraft:obsidian' : 'minecraft:water'
      await command(phaseBot, `/fill ${x} 65 -3 ${x} 69 3 ${material}`, 30)
    }
  } else if (trial.kind === 'mixed') {
    const palette = ['minecraft:obsidian', 'minecraft:water', 'minecraft:obsidian', 'minecraft:lava']
    for (let x = WALL_START; x <= wallEnd; x++) {
      const material = palette[(x - WALL_START) % palette.length]
      await command(phaseBot, `/fill ${x} 65 -3 ${x} 69 3 ${material}`, 30)
    }
  } else {
    throw new Error(`Unknown course kind ${trial.kind}`)
  }

  // Horse-sized sealed chamber. The only intended entry path is through the wall.
  await command(phaseBot, `/fill ${chamberX - 1} 64 -4 ${chamberX + 7} 70 4 minecraft:obsidian`, 300)
  await command(phaseBot, `/fill ${chamberX} 65 -3 ${chamberX + 6} 69 3 minecraft:air`, 250)
  await command(phaseBot, `/summon minecraft:item ${chamberX + 3.0} 65 ${Z} {Item:{id:"minecraft:netherite_block",count:1}}`, 150)
  return { wallEnd, chamberX, targetX: chamberX + 3.0 }
}

async function resetAttacker (phaseBot, attackerBot) {
  if (attackerBot.vehicle) {
    try { attackerBot.dismount() } catch {}
    await sleep(200)
  }
  await command(phaseBot, '/kill @e[type=minecraft:oak_boat]', 100)
  await command(phaseBot, '/kill @e[type=minecraft:horse]', 150)
  await command(phaseBot, '/kill @e[type=minecraft:item]', 100)
  await command(phaseBot, '/clear AttackerBot', 100)
  await command(phaseBot, `/tp AttackerBot 14.25 ${Y} ${Z} -90 0`, 350)
}

async function waitForInventoryItem (bot, itemName, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const item = bot.inventory.items().find(entry => entry.name === itemName)
    if (item) return item
    await sleep(100)
  }
  return null
}

async function waitForHorse (bot, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const candidate = Object.values(bot.entities).find(entity => {
      if (!entity || !entity.position) return false
      const label = `${entity.name || ''} ${entity.displayName || ''}`.toLowerCase()
      return label.includes('horse') && entity.position.distanceTo(bot.entity.position) < 8
    })
    if (candidate) return candidate
    await sleep(100)
  }
  return null
}

async function horsePlaceAndMount (phaseBot, attackerBot) {
  await command(phaseBot, `/tp AttackerBot 13.25 ${Y} ${Z} -90 0`, 350)
  const prep = await commandExpect(
    phaseBot,
    '/stacklab horseprep AttackerBot',
    /STACKLAB HORSE PREP .*"saddled":true.*"fire_resistance":true/,
    8000
  )
  record('server_horse_prep_response', { prep })
  const horse = await waitForHorse(attackerBot, 8000)
  if (!horse) throw new Error('Prepared horse was not visible to AttackerBot')

  const mounted = onceWithTimeout(attackerBot, 'mount', 2500).catch(() => null)
  const interaction = await commandExpect(
    phaseBot,
    '/stacklab vehicleinteract AttackerBot HORSE',
    /STACKLAB VEHICLE INTERACT .*"mounted":true.*"vehicle_type":"HORSE"/,
    6000
  )
  record('server_horse_interact_response', { interaction })
  await mounted
  await sleep(300)
  const check = await commandExpect(
    phaseBot,
    '/stacklab vehiclecheck AttackerBot',
    /STACKLAB VEHICLE CHECK /,
    4000
  )
  if (!check.includes('"mounted":true') || !check.includes('"vehicle_type":"HORSE"')) {
    throw new Error(`Horse mount was not server-authoritative check=${check}`)
  }
  if (!attackerBot.vehicle) {
    attackerBot.vehicle = horse
    attackerBot.entity.vehicle = horse
    if (!horse.passengers.includes(attackerBot.entity)) horse.passengers.push(attackerBot.entity)
    record('horse_mount_client_state_repaired', { horseId: horse.id })
  }
  record('survival_horse_ready', {
    placement: 'tamed_saddled_fire_resistant_horse',
    mount: 'ServerboundInteractPacket',
    horseId: attackerBot.vehicle.id,
    horsePosition: attackerBot.vehicle.position,
    playerPosition: attackerBot.entity.position
  })
  return attackerBot.vehicle
}

async function spawnAndMount (phaseBot, attackerBot, trial) {
  if (trial.vehicle === 'horse') return await horsePlaceAndMount(phaseBot, attackerBot)
  throw new Error(`Unsupported vehicle ${trial.vehicle}`)
}

async function sendVehicleRange (bot, startX, targetX, step, delayMs, correctionRef) {
  let packets = 0
  for (let x = startX + step; x < targetX && bot.vehicle && !correctionRef.value; x += step) {
    bot.vehicle.position.set(x, Y, Z)
    bot.entity.position.set(x, Y, Z)
    bot._client.write('vehicle_move', { x, y: Y, z: Z, yaw: -90, pitch: 0, onGround: true })
    packets++
    if (delayMs > 0) await sleep(delayMs)
    else if (packets % 30 === 0) await new Promise(resolve => setImmediate(resolve))
  }
  if (bot.vehicle && !correctionRef.value) {
    bot.vehicle.position.set(targetX, Y, Z)
    bot.entity.position.set(targetX, Y, Z)
    bot._client.write('vehicle_move', { x: targetX, y: Y, z: Z, yaw: -90, pitch: 0, onGround: true })
    packets++
  }
  return packets
}

async function sendVehicleSequence (phaseBot, bot, startX, targetX, trial, correctionRef) {
  if (!trial.segmentLength) {
    return {
      packetCount: await sendVehicleRange(bot, startX, targetX, trial.step, trial.delayMs, correctionRef),
      segmentWitnesses: []
    }
  }

  let packetCount = 0
  let acceptedX = startX
  const segmentWitnesses = []
  let segment = 0
  while (acceptedX < targetX - 1e-9 && bot.vehicle && !correctionRef.value) {
    segment++
    const segmentTarget = Math.min(targetX, acceptedX + trial.segmentLength)
    packetCount += await sendVehicleRange(bot, acceptedX, segmentTarget, trial.step, trial.delayMs, correctionRef)
    await sleep(trial.segmentPauseMs || 100)

    const minX = segmentTarget - 0.9
    const playerSelector = `@a[name=AttackerBot,x=${minX},y=64,z=-2,dx=2,dy=5,dz=4,limit=1]`
    const vehicleSelector = `@e[type=minecraft:horse,x=${minX},y=64,z=-2,dx=2,dy=5,dz=4,limit=1]`
    const playerAccepted = await serverWitness(phaseBot, playerSelector, `SEG_PLAYER_${trial.id}_${segment}`)
    const vehicleAccepted = await serverWitness(phaseBot, vehicleSelector, `SEG_BOAT_${trial.id}_${segment}`)
    const witness = {
      segment,
      fromX: acceptedX,
      targetX: segmentTarget,
      playerAccepted,
      vehicleAccepted,
      correctionsSoFar: correctionRef.value
    }
    segmentWitnesses.push(witness)
    record('vehicle_segment_witness', { trial: trial.id, ...witness })
    if (!playerAccepted || !vehicleAccepted || correctionRef.value) break
    acceptedX = segmentTarget
  }
  return { packetCount, segmentWitnesses }
}

async function runTrial (phaseBot, attackerBot, trial, run) {
  await resetAttacker(phaseBot, attackerBot)
  const course = await buildCourse(phaseBot, trial)
  const boat = await spawnAndMount(phaseBot, attackerBot, trial)
  const startX = boat.position.x
  const corrections = captureCorrections(attackerBot, boat.id)
  const correctionRef = { value: false }
  const correctionWatcher = setInterval(() => {
    correctionRef.value = corrections.events.length > 0
  }, 1)

  const started = Date.now()
  const sequence = await sendVehicleSequence(phaseBot, attackerBot, startX, course.targetX, trial, correctionRef)
  const packetCount = sequence.packetCount
  await sleep(350)
  clearInterval(correctionWatcher)

  const playerSelector = `@a[name=AttackerBot,x=${course.chamberX},y=64,z=-4,dx=6,dy=7,dz=8,limit=1]`
  const vehicleSelector = `@e[type=minecraft:horse,x=${course.chamberX},y=64,z=-4,dx=6,dy=7,dz=8,limit=1]`
  const playerBeyondMounted = await serverWitness(phaseBot, playerSelector, `PLAYER_MOUNTED_${trial.id}_${run}`)
  const vehicleBeyond = await serverWitness(phaseBot, vehicleSelector, `BOAT_${trial.id}_${run}`)

  let dismountError = null
  let dismountResponse = null
  try {
    dismountResponse = await commandExpect(
      phaseBot,
      '/stacklab vehicledismount AttackerBot',
      /STACKLAB VEHICLE DISMOUNT .*"mounted":false/,
      5000
    )
    attackerBot.vehicle = null
    attackerBot.entity.vehicle = null
  } catch (error) {
    dismountError = String(error.stack || error)
  }
  await sleep(1000)
  const playerBeyondDismounted = await serverWitness(phaseBot, playerSelector, `PLAYER_DISMOUNTED_${trial.id}_${run}`)
  const netheriteCount = attackerBot.inventory.items()
    .filter(item => item.name === 'netherite_block')
    .reduce((sum, item) => sum + item.count, 0)

  corrections.stop()
  const result = {
    id: trial.id,
    run,
    kind: trial.kind,
    thickness: trial.thickness,
    step: trial.step,
    delayMs: trial.delayMs,
    placement: trial.placement || 'fixture',
    startX,
    segmentLength: trial.segmentLength || null,
    segmentPauseMs: trial.segmentPauseMs || null,
    elapsedMs: Date.now() - started,
    packetCount,
    segmentWitnesses: sequence.segmentWitnesses,
    playerBeyondMounted,
    vehicleBeyond,
    playerBeyondDismounted,
    netheriteCount,
    mountedAfter: Boolean(attackerBot.vehicle),
    dismountError,
    dismountResponse,
    correctionCount: corrections.events.length,
    firstCorrection: corrections.events[0] || null,
    clientPlayerPosition: attackerBot.entity.position,
    clientBoatPosition: attackerBot.vehicle ? attackerBot.vehicle.position : null
  }
  result.serverAuthoritativeSuccess = Boolean(
    playerBeyondMounted && vehicleBeyond && playerBeyondDismounted && netheriteCount >= 1
  )
  record('vehicle_trial', result)
  report.trials.push(result)
  return result
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const victimBot = await connect('VictimBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, victimBot, attackerBot]

  const trialPlan = [
    { id: 'solid240-horse-control', kind: 'solid', vehicle: 'horse', thickness: 240, step: 0.25, delayMs: 0, segmentLength: 15, segmentPauseMs: 100, repeats: 1 },
    { id: 'mixed64-horse-ratchet10', kind: 'mixed', vehicle: 'horse', thickness: 64, step: 0.25, delayMs: 0, segmentLength: 10, segmentPauseMs: 100, repeats: 3 },
    { id: 'mixed240-horse-ratchet10', kind: 'mixed', vehicle: 'horse', thickness: 240, step: 0.25, delayMs: 0, segmentLength: 10, segmentPauseMs: 100, repeats: 2 }
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
    await setupFactions(phaseBot, victimBot, attackerBot)

    for (const trial of trialPlan) {
      for (let run = 1; run <= trial.repeats; run++) {
        try {
          await runTrial(phaseBot, attackerBot, trial, run)
        } catch (error) {
          const failure = {
            id: trial.id,
            run,
            kind: trial.kind,
            thickness: trial.thickness,
            step: trial.step,
            delayMs: trial.delayMs,
            serverAuthoritativeSuccess: false,
            error: String(error.stack || error)
          }
          report.trials.push(failure)
          record('vehicle_trial_error', failure)
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
    fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-horse-phase-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-horse-phase-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab complete') } catch {}
    }
  }

  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-horse-phase-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
