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

async function command (bot, text, delay = 110) {
  bot.chat(text)
  await sleep(delay)
}

async function setup (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, '/claimlab zone 0 239.999')
}

async function reset (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 1200)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 100)
  const position = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s ${RESET_X} ${Y} ${Z}`)
  if (!await position) throw new Error('Reset position packet missing')
  await command(bot, '/claimlab reset', 60)
  await command(bot, '/courselab reset', 60)
  await sleep(100)
}

async function prepareCourse (bot, profile, mode) {
  await command(bot, `/claimlab mode ${mode}`)
  await command(bot, `/claimlab relation ${USERNAME} enemy`)
  await command(bot, `/courselab build ${profile}`, 2600)
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
    packet: packetPosition(packet),
    clientX: bot.entity.position.x
  })
  const vehicleHandler = packet => vehicleCorrections.push({
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    packet
  })
  const teleportHandler = packet => {
    if (packet.entityId === boatId) {
      boatTeleports.push({
        elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
        packet
      })
    }
  }
  const dismountHandler = vehicle => dismounts.push({
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    vehicleId: vehicle?.id ?? null
  })
  const goneHandler = entity => {
    if (entity.id === boatId) {
      gone.push({
        elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
        id: entity.id
      })
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
  let maxRequestedX = BOAT_X
  let ticks = 0
  const checkpoints = []
  const started = process.hrtime.bigint()

  while (x < TARGET_X - 1e-9 && bot.vehicle && bot.entities[boat.id]) {
    let sentThisTick = 0
    while (sentThisTick < plan.batchSize && x < TARGET_X - 1e-9 && bot.vehicle && bot.entities[boat.id]) {
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
      sentThisTick++
      maxRequestedX = x
      x += STEP
    }
    ticks++
    await sleep(TICK_MS)

    if (ticks % 8 === 0 || Math.floor(maxRequestedX / 16) !== Math.floor((maxRequestedX - plan.batchSize * STEP) / 16)) {
      checkpoints.push({
        tick: ticks,
        maxRequestedX,
        playerX: bot.entity.position.x,
        boatX: bot.vehicle ? bot.vehicle.position.x : null,
        mounted: Boolean(bot.vehicle),
        boatExists: Boolean(bot.entities[boat.id]),
        health: bot.health,
        food: bot.food,
        playerCorrections: capture.playerCorrections.length,
        vehicleCorrections: capture.vehicleCorrections.length,
        dismounts: capture.dismounts.length,
        gone: capture.gone.length
      })
    }

    if (plan.stopOnCorrection && (capture.playerCorrections.length > 0 || capture.vehicleCorrections.length > 0)) {
      break
    }
    if (capture.gone.length > 0) break
  }

  if (bot.vehicle && bot.entities[boat.id] && maxRequestedX < TARGET_X) {
    boat.position.set(TARGET_X, Y, Z)
    bot.entity.position.set(TARGET_X, Y, Z)
    bot._client.write('vehicle_move', {
      x: TARGET_X,
      y: Y,
      z: Z,
      yaw: -90,
      pitch: 0,
      onGround: true
    })
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

async function authoritativePlayerSnapshot (bot) {
  const packetPromise = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  await sleep(100)
  return {
    packet: args ? packetPosition(args[0]) : null,
    position: {
      x: bot.entity.position.x,
      y: bot.entity.position.y,
      z: bot.entity.position.z
    },
    health: bot.health,
    food: bot.food
  }
}

async function dismountAndSnapshot (bot) {
  let dismounted = false
  if (bot.vehicle) {
    const dismountPromise = onceWithTimeout(bot, 'dismount', 1800)
    bot.dismount()
    dismounted = Boolean(await dismountPromise)
  }
  await sleep(250)
  const snapshot = await authoritativePlayerSnapshot(bot)
  return { dismounted, snapshot }
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
  await reset(bot)
  await prepareCourse(bot, plan.profile, plan.mode)
  const boat = await summonAndMount(bot, plan.invulnerable)
  if (!boat) {
    return {
      ...plan,
      id,
      mounted: false,
      send: null,
      runtime: null,
      exit: null,
      witness: { opened: false, reason: 'mount_failed' },
      verified: false
    }
  }

  await command(bot, `/courselab start ${id}-${plan.profile}-${plan.mode}`, 90)
  const capture = captureRuntime(bot, boat.id)
  const send = await sendCourse(bot, boat, plan, capture)
  await sleep(700)
  const stillMountedAfterSend = Boolean(bot.vehicle)
  const boatExistsAfterSend = Boolean(bot.entities[boat.id])
  const exit = await dismountAndSnapshot(bot)
  capture.stop()
  await command(bot, '/courselab stop', 60)

  const beyondCourse = exit.snapshot.position.x > COURSE_END + 0.50
  const alive = exit.snapshot.health > 0
  const witness = beyondCourse && alive
    ? await openWitness(bot)
    : { opened: false, reason: alive ? 'not_beyond_course' : 'dead_or_zero_health' }

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
    exit,
    beyondCourse,
    alive,
    witness,
    verified: beyondCourse && alive && exit.dismounted && witness.opened
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'mixed-claim-course-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      course: [0, COURSE_END],
      step: STEP,
      targetX: TARGET_X,
      witness: WITNESS,
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['id,profile,mode,batch,stop_on_correction,invulnerable,mounted,packets,ticks,send_ms,max_requested_x,player_corrections,vehicle_corrections,boat_teleports,dismount_events,boat_gone,still_mounted,boat_exists,dismounted,post_x,post_y,post_z,health,alive,beyond,witness,verified']
  for (const result of results) {
    rows.push([
      result.id,
      result.profile,
      result.mode,
      result.batchSize,
      result.stopOnCorrection,
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
      result.exit?.dismounted ?? '',
      result.exit?.snapshot?.position?.x?.toFixed(6) ?? '',
      result.exit?.snapshot?.position?.y?.toFixed(6) ?? '',
      result.exit?.snapshot?.position?.z?.toFixed(6) ?? '',
      result.exit?.snapshot?.health ?? '',
      result.alive ?? '',
      result.beyondCourse ?? '',
      result.witness.opened,
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
  const bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username: USERNAME,
    auth: 'offline',
    version: '1.21.11',
    physicsEnabled: false,
    hideErrors: false
  })
  bot.on('kicked', reason => console.error('[MixedCourse kicked]', reason))
  bot.on('error', error => console.error('[MixedCourse error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Mixed course bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
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
    for (let id = 0; id < plans.length; id++) {
      const result = await runTrial(bot, plans[id], id)
      results.push(result)
      writeReport(results, bot)
      console.log(`[MixedCourse] ${id + 1}/${plans.length}` +
        ` profile=${result.profile} mode=${result.mode}` +
        ` batch=${result.batchSize} invuln=${result.invulnerable}` +
        ` maxX=${result.send?.maxRequestedX?.toFixed(2) ?? 'none'}` +
        ` postX=${result.exit?.snapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` health=${result.exit?.snapshot?.health ?? 'none'}` +
        ` corrections=${result.runtime?.playerCorrections?.length ?? 0}/${result.runtime?.vehicleCorrections?.length ?? 0}` +
        ` boatGone=${result.runtime?.gone?.length ?? 0}` +
        ` verified=${result.verified}`)
    }

    const verified = results.filter(result => result.verified).length
    console.log(`[MixedCourse] completed=${results.length} verified=${verified}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[MixedCourse fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
