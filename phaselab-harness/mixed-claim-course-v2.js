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
const Y = 65
const Z = 0.50
const STEP = 0.25
const TARGET_X = 240.72
const COURSE_END = 239.999
const WITNESS = new Vec3(244, 65, 0)
const TICK_MS = 50

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

function messageWithPrefix (bot, prefix, timeoutMs = 1800) {
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

async function command (bot, text, delay = 110) {
  bot.chat(text)
  await sleep(delay)
}

async function serverSnapshot (bot) {
  const messagePromise = messageWithPrefix(bot, 'COURSE_SNAPSHOT ', 2200)
  bot.chat('/courselab snapshot')
  const line = await messagePromise
  if (!line) {
    return { ok: false, line: null, position: null, health: null, fire: null, vehicle: null }
  }
  const match = line.match(/player=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?) health=(-?\d+(?:\.\d+)?) fire=(-?\d+) vehicle=(none|-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?)/)
  if (!match) {
    return { ok: false, line, position: null, health: null, fire: null, vehicle: null }
  }
  const vehicle = match[6] === 'none'
    ? null
    : (() => {
        const [x, y, z] = match[6].split(',').map(Number)
        return { x, y, z }
      })()
  return {
    ok: true,
    line,
    position: { x: Number(match[1]), y: Number(match[2]), z: Number(match[3]) },
    health: Number(match[4]),
    fire: Number(match[5]),
    vehicle
  }
}

async function setup (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, '/claimlab zone 0 239.999')
}

const RESET_EPSILON = 0.75
const RESET_ATTEMPTS = 4

// Retired false-positive rule 3: a relative zero-delta /tp is not an authoritative
// coordinate snapshot, and rule 1: a missing packet is not a state claim. The reset
// verdict therefore comes from the server snapshot, never from the position packet.
async function verifyReset (bot) {
  const snap = await serverSnapshot(bot)
  if (!snap.ok || !snap.position) return { ok: false, reason: 'snapshot_unavailable', snap }
  if (snap.vehicle) return { ok: false, reason: 'still_mounted', snap }
  if (Math.abs(snap.position.x - RESET_X) > RESET_EPSILON) {
    return { ok: false, reason: `off_anchor:${snap.position.x.toFixed(3)}`, snap }
  }
  return { ok: true, reason: 'clean', snap }
}

async function reset (bot, attempts = RESET_ATTEMPTS) {
  let last = { ok: false, reason: 'not_attempted', snap: null, attempt: 0, positionPacket: false }
  for (let attempt = 1; attempt <= attempts; attempt++) {
    if (bot.vehicle) {
      const dismounted = onceWithTimeout(bot, 'dismount', 1200)
      bot.chat('/ride @s dismount')
      await dismounted
    }
    await command(bot, '/kill @e[type=minecraft:oak_boat]', 100)

    const position = onceWithTimeout(bot._client, 'position', 2500)
    bot.chat(`/tp @s ${RESET_X} ${Y} ${Z}`)
    const packet = await position
    if (!packet) await sleep(400)

    await command(bot, '/claimlab reset', 60)
    await command(bot, '/courselab reset', 60)

    last = await verifyReset(bot)
    last.attempt = attempt
    last.positionPacket = Boolean(packet)
    if (last.ok) return last
    console.warn(`[MixedCourse reset] attempt ${attempt}/${attempts} unclean: ${last.reason}` +
      ` positionPacket=${Boolean(packet)}`)
    await sleep(500)
  }
  return last
}

async function prepareCourse (bot, profile, mode) {
  await command(bot, `/claimlab mode ${mode}`)
  await command(bot, `/claimlab relation ${USERNAME} enemy`)
  await command(bot, `/courselab build ${profile}`, 2800)
}

async function summonAndMount (bot, invulnerable) {
  const nbt = invulnerable ? '{Rotation:[-90f,0f],Invulnerable:1b}' : '{Rotation:[-90f,0f]}'
  bot.chat(`/summon minecraft:oak_boat ${BOAT_X} ${Y} ${Z} ${nbt}`)
  await sleep(160)
  let mounted = onceWithTimeout(bot, 'mount', 1800)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  if (!bot.vehicle) {
    mounted = onceWithTimeout(bot, 'mount', 1000)
    bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
    await mounted
  }
  await sleep(120)
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

function captureRuntime (bot, boatId) {
  const started = process.hrtime.bigint()
  const playerCorrections = []
  const vehicleCorrections = []
  const boatTeleports = []
  const dismounts = []
  const gone = []

  const playerHandler = packet => playerCorrections.push({
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    packet: packetPosition(packet)
  })
  const vehicleHandler = packet => vehicleCorrections.push({
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    packet
  })
  const teleportHandler = packet => {
    if (packet.entityId === boatId) {
      boatTeleports.push({ elapsedMs: Number(process.hrtime.bigint() - started) / 1e6, packet })
    }
  }
  const dismountHandler = vehicle => dismounts.push({
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    vehicleId: vehicle?.id ?? null
  })
  const goneHandler = entity => {
    if (entity.id === boatId) {
      gone.push({ elapsedMs: Number(process.hrtime.bigint() - started) / 1e6, id: entity.id })
    }
  }

  bot._client.on('position', playerHandler)
  bot._client.on('vehicle_move', vehicleHandler)
  bot._client.on('entity_teleport', teleportHandler)
  bot.on('dismount', dismountHandler)
  bot.on('entityGone', goneHandler)

  return {
    playerCorrections,
    vehicleCorrections,
    boatTeleports,
    dismounts,
    gone,
    stop () {
      bot._client.removeListener('position', playerHandler)
      bot._client.removeListener('vehicle_move', vehicleHandler)
      bot._client.removeListener('entity_teleport', teleportHandler)
      bot.removeListener('dismount', dismountHandler)
      bot.removeListener('entityGone', goneHandler)
    }
  }
}

async function sendCourse (bot, boat, plan, capture) {
  let x = BOAT_X + STEP
  let packets = 0
  let ticks = 0
  let maxRequestedX = BOAT_X
  const checkpoints = []
  const started = process.hrtime.bigint()

  while (x < TARGET_X - 1e-9 && bot.vehicle && bot.entities[boat.id]) {
    let sent = 0
    while (sent < plan.batchSize && x < TARGET_X - 1e-9 && bot.vehicle && bot.entities[boat.id]) {
      boat.position.set(x, Y, Z)
      bot.entity.position.set(x, Y, Z)
      bot._client.write('vehicle_move', { x, y: Y, z: Z, yaw: -90, pitch: 0, onGround: true })
      packets++
      sent++
      maxRequestedX = x
      x += STEP
    }
    ticks++
    await sleep(TICK_MS)

    if (ticks % 8 === 0) {
      checkpoints.push({
        tick: ticks,
        maxRequestedX,
        mounted: Boolean(bot.vehicle),
        boatExists: Boolean(bot.entities[boat.id]),
        playerCorrections: capture.playerCorrections.length,
        vehicleCorrections: capture.vehicleCorrections.length,
        dismounts: capture.dismounts.length,
        gone: capture.gone.length
      })
    }

    if (plan.stopOnCorrection && (capture.playerCorrections.length || capture.vehicleCorrections.length)) break
    if (capture.gone.length) break
  }

  if (bot.vehicle && bot.entities[boat.id] && maxRequestedX < TARGET_X) {
    boat.position.set(TARGET_X, Y, Z)
    bot.entity.position.set(TARGET_X, Y, Z)
    bot._client.write('vehicle_move', { x: TARGET_X, y: Y, z: Z, yaw: -90, pitch: 0, onGround: true })
    packets++
    maxRequestedX = TARGET_X
    await sleep(TICK_MS)
  }

  return {
    packets,
    ticks,
    maxRequestedX,
    checkpoints,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6
  }
}

async function dismount (bot) {
  if (!bot.vehicle) return false
  const promise = onceWithTimeout(bot, 'dismount', 1800)
  bot.dismount()
  return Boolean(await promise)
}

async function openWitness (bot) {
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 90)
  let block = bot.blockAt(WITNESS)
  for (let attempt = 0; attempt < 20 && (!block || block.name !== 'barrel'); attempt++) {
    await sleep(100)
    block = bot.blockAt(WITNESS)
  }
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  }
  const opened = onceWithTimeout(bot, 'windowOpen', 1600)
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
  const resetState = await reset(bot)
  await prepareCourse(bot, plan.profile, plan.mode)
  const boat = await summonAndMount(bot, plan.invulnerable)
  if (!boat) {
    return {
      ...plan,
      id,
      mounted: false,
      verified: false,
      reason: 'mount_failed',
      resetOk: resetState.ok,
      resetReason: resetState.reason,
      resetAttempts: resetState.attempt
    }
  }

  await command(bot, `/courselab start ${id}-${plan.profile}-${plan.mode}`, 90)
  const capture = captureRuntime(bot, boat.id)
  const send = await sendCourse(bot, boat, plan, capture)
  await sleep(700)
  const stillMountedAfterSend = Boolean(bot.vehicle)
  const boatExistsAfterSend = Boolean(bot.entities[boat.id])
  const didDismount = await dismount(bot)
  await sleep(250)
  const snapshot = await serverSnapshot(bot)
  const witness = await openWitness(bot)
  capture.stop()
  await command(bot, '/courselab stop', 60)

  const beyondCourse = snapshot.ok && snapshot.position.x > COURSE_END + 0.50
  const alive = snapshot.ok && snapshot.health > 0
  return {
    ...plan,
    id,
    mounted: true,
    stillMountedAfterSend,
    boatExistsAfterSend,
    send,
    runtime: {
      playerCorrections: capture.playerCorrections,
      vehicleCorrections: capture.vehicleCorrections,
      boatTeleports: capture.boatTeleports,
      dismounts: capture.dismounts,
      gone: capture.gone
    },
    didDismount,
    snapshot,
    beyondCourse,
    alive,
    witness,
    resetOk: resetState.ok,
    resetReason: resetState.reason,
    resetAttempts: resetState.attempt,
    kickedDuringTrial: isDead(bot),
    kickReason: lastKick,
    verified: resetState.ok && !isDead(bot) && snapshot.ok && beyondCourse && alive &&
      didDismount && witness.opened
  }
}

let lastKick = null

function isDead (bot) {
  return !bot || !bot._client || bot._client.ended
}

function describeKick (reason) {
  try {
    const translate = reason?.value?.translate?.value
    if (translate) return translate
    return JSON.stringify(reason).slice(0, 200)
  } catch (_) {
    return String(reason).slice(0, 200)
  }
}

async function connect () {
  const bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username: USERNAME,
    auth: 'offline',
    version: '1.21.11',
    physicsEnabled: false,
    hideErrors: false
  })
  bot.on('kicked', reason => {
    lastKick = describeKick(reason)
    console.error('[MixedCourse kicked]', lastKick)
  })
  bot.on('error', error => console.error('[MixedCourse error]', error?.message ?? error))
  bot.on('end', why => console.warn('[MixedCourse end]', why))
  const spawned = await onceWithTimeout(bot, 'spawn', 30000)
  if (!spawned) throw new Error('Mixed course bot did not spawn')
  bot.physicsEnabled = false
  await sleep(900)
  return bot
}

// allow-flight stays false so the lab keeps production fidelity. A vanilla
// anti-fly kick is therefore a real outcome for that trial, not a harness
// defect, so record it and reconnect instead of running the rest of the
// matrix against a dead socket.
async function reconnect (attempts = 3) {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      const bot = await connect()
      await setup(bot)
      console.warn(`[MixedCourse] reconnected on attempt ${attempt}`)
      return bot
    } catch (error) {
      console.error(`[MixedCourse] reconnect attempt ${attempt}/${attempts} failed: ${error.message}`)
      await sleep(2000)
    }
  }
  return null
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'mixed-claim-course-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      course: [0, COURSE_END],
      targetX: TARGET_X,
      step: STEP,
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['id,profile,mode,batch,invulnerable,mounted,packets,ticks,send_ms,max_requested_x,player_corrections,vehicle_corrections,boat_teleports,dismount_events,boat_gone,still_mounted,boat_exists,did_dismount,snapshot_ok,server_x,server_y,server_z,server_health,server_fire,beyond,witness,reset_ok,reset_reason,kicked,kick_reason,trial_error,verified']
  for (const result of results) {
    rows.push([
      result.id,
      result.profile,
      result.mode,
      result.batchSize,
      result.invulnerable,
      result.mounted,
      result.send?.packets ?? '',
      result.send?.ticks ?? '',
      result.send ? result.send.elapsedMs.toFixed(3) : '',
      result.send ? result.send.maxRequestedX.toFixed(6) : '',
      result.runtime?.playerCorrections?.length ?? '',
      result.runtime?.vehicleCorrections?.length ?? '',
      result.runtime?.boatTeleports?.length ?? '',
      result.runtime?.dismounts?.length ?? '',
      result.runtime?.gone?.length ?? '',
      result.stillMountedAfterSend ?? '',
      result.boatExistsAfterSend ?? '',
      result.didDismount ?? '',
      result.snapshot?.ok ?? '',
      result.snapshot?.position?.x?.toFixed(6) ?? '',
      result.snapshot?.position?.y?.toFixed(6) ?? '',
      result.snapshot?.position?.z?.toFixed(6) ?? '',
      result.snapshot?.health ?? '',
      result.snapshot?.fire ?? '',
      result.beyondCourse ?? '',
      result.witness?.opened ?? '',
      result.resetOk ?? '',
      result.resetReason ?? '',
      result.kickedDuringTrial ?? '',
      result.kickReason ? JSON.stringify(result.kickReason) : '',
      result.trialError ? JSON.stringify(result.trialError) : '',
      result.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'mixed-claim-course-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab mixed course complete')
  } catch (_) {}
  await sleep(300)
  process.exit(code)
}

async function main () {
  let bot = await connect()

  try {
    await setup(bot)

    const plans = []
    for (const profile of ['mixed', 'water_heavy', 'lava_heavy']) {
      plans.push({ profile, mode: 'observe', batchSize: 10, stopOnCorrection: true, invulnerable: false })
      plans.push({ profile, mode: 'observe', batchSize: 20, stopOnCorrection: true, invulnerable: false })
      plans.push({ profile, mode: 'observe', batchSize: 20, stopOnCorrection: true, invulnerable: true })
      plans.push({ profile, mode: 'likely', batchSize: 10, stopOnCorrection: false, invulnerable: false })
      plans.push({ profile, mode: 'likely', batchSize: 20, stopOnCorrection: false, invulnerable: false })
      plans.push({ profile, mode: 'strict', batchSize: 10, stopOnCorrection: false, invulnerable: false })
    }

    const results = []
    let reconnects = 0
    for (let id = 0; id < plans.length; id++) {
      lastKick = null

      if (isDead(bot)) {
        const revived = await reconnect()
        if (!revived) {
          results.push({
            ...plans[id],
            id,
            mounted: false,
            verified: false,
            resetOk: false,
            resetReason: 'reconnect_failed',
            trialError: 'bot offline and reconnect failed'
          })
          console.error(`[MixedCourse] ${id + 1}/${plans.length} skipped, reconnect failed`)
          continue
        }
        bot = revived
        reconnects++
      }

      let result
      try {
        result = await runTrial(bot, plans[id], id)
      } catch (error) {
        console.error(`[MixedCourse trial ${id} error]`, error && error.message ? error.message : error)
        result = {
          ...plans[id],
          id,
          mounted: false,
          verified: false,
          trialError: String(error && error.message ? error.message : error)
        }
        result.kickedDuringTrial = isDead(bot)
        result.kickReason = lastKick
        if (!isDead(bot)) {
          try {
            const recovery = await reset(bot)
            result.resetOk = recovery.ok
            result.resetReason = `recovery:${recovery.reason}`
          } catch (recoveryError) {
            result.resetOk = false
            result.resetReason = `recovery_failed:${recoveryError.message}`
          }
        } else {
          result.resetOk = false
          result.resetReason = 'offline_after_trial'
        }
      }
      results.push(result)
      writeReport(results, bot)
      console.log(`[MixedCourse] ${id + 1}/${plans.length}` +
        ` profile=${result.profile} mode=${result.mode} batch=${result.batchSize}` +
        ` serverX=${result.snapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` health=${result.snapshot?.health ?? 'none'}` +
        ` corrections=${result.runtime?.playerCorrections?.length ?? 0}/${result.runtime?.vehicleCorrections?.length ?? 0}` +
        ` boatGone=${result.runtime?.gone?.length ?? 0}` +
        ` witness=${result.witness?.opened ?? false}` +
        ` reset=${result.resetOk ?? 'n/a'}` +
        (result.kickedDuringTrial ? ` KICKED=${result.kickReason}` : '') +
        (result.trialError ? ` error=${JSON.stringify(result.trialError)}` : '') +
        ` verified=${result.verified}`)
    }

    const breaches = results.filter(r => r.verified)
    const uncleanResets = results.filter(r => r.resetOk === false)
    const errored = results.filter(r => r.trialError)
    const kicked = results.filter(r => r.kickedDuringTrial)
    console.log(`[MixedCourse] completed=${results.length}/${plans.length}` +
      ` verified=${breaches.length} uncleanResets=${uncleanResets.length}` +
      ` erroredTrials=${errored.length} kicked=${kicked.length} reconnects=${reconnects}`)
    for (const r of kicked) {
      console.log(`[MixedCourse VANILLA-STOP] id=${r.id} profile=${r.profile} mode=${r.mode}` +
        ` batch=${r.batchSize} reason=${r.kickReason}`)
    }
    for (const r of results) {
      const x = r.snapshot?.position?.x
      if (typeof x === 'number' && x > 0 && x <= COURSE_END && !r.trialError) {
        console.log(`[MixedCourse INSIDE-CLAIM] id=${r.id} profile=${r.profile} mode=${r.mode}` +
          ` batch=${r.batchSize} finalX=${x.toFixed(6)} corrections=` +
          `${r.runtime?.playerCorrections?.length ?? 0}/${r.runtime?.vehicleCorrections?.length ?? 0}`)
      }
    }
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[MixedCourse fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
