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
const Y = 65
const Z = 0.50
const MAX_X = 246
const STEP = 0.25
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

async function command (bot, text, delay = 100) {
  bot.chat(text)
  await sleep(delay)
}

async function setupBase (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, `/fill -5 63 -5 ${MAX_X} 72 5 minecraft:air`, 350)
  await command(bot, `/fill -4 64 -4 ${MAX_X} 64 4 minecraft:stone`, 350)
}

async function buildCourse (bot, course) {
  await command(bot, `/fill 1 65 -3 ${MAX_X} 69 3 minecraft:air`, 250)
  if (course.kind === 'solid') {
    await command(bot, `/fill 1 65 -3 ${course.thickness} 69 3 minecraft:obsidian`, 1000)
  } else {
    await command(bot, `/fill 1 65 -3 ${course.thickness} 69 3 minecraft:obsidian`, 500)
    for (let x = 2; x <= course.thickness; x += 2) {
      await command(bot, `/fill ${x} 65 -3 ${x} 69 3 minecraft:water`, 40)
    }
  }
  const witness = new Vec3(course.thickness + 3, 65, 0)
  await command(bot, `/setblock ${witness.x} ${witness.y} ${witness.z} minecraft:barrel[facing=west]`, 160)
  return {
    ...course,
    targetX: course.thickness + 0.72,
    boundaryX: course.thickness + 0.70,
    witness
  }
}

async function reset (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 1800)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 120)
  const position = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s -1.25 ${Y} ${Z}`)
  if (!await position) throw new Error('Reset teleport packet missing')
  await sleep(120)
}

async function mountBoat (bot) {
  bot.chat(`/summon minecraft:oak_boat ${START_X} ${Y} ${Z} {Rotation:[-90f,0f],Invulnerable:1b}`)
  await sleep(160)
  let mounted = onceWithTimeout(bot, 'mount', 2200)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  if (!bot.vehicle) {
    mounted = onceWithTimeout(bot, 'mount', 2200)
    bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
    await mounted
  }
  if (!bot.vehicle) throw new Error('Boat mount fixture failed')
  await sleep(120)
  return bot.vehicle
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
  const entityTeleport = packet => {
    if (packet.entityId === boatId) add('boat_entity_teleport', packet)
  }
  bot._client.on('vehicle_move', vehicleMove)
  bot._client.on('position', playerPosition)
  bot._client.on('entity_teleport', entityTeleport)
  return {
    events,
    stop () {
      bot._client.removeListener('vehicle_move', vehicleMove)
      bot._client.removeListener('position', playerPosition)
      bot._client.removeListener('entity_teleport', entityTeleport)
    }
  }
}

async function sendBatches (bot, targetX, trial, corrected) {
  let x = START_X + STEP
  let packets = 0
  let batchPackets = 0
  const started = process.hrtime.bigint()

  while (x < targetX - 1e-9 && !corrected() && bot.vehicle) {
    bot.vehicle.position.set(x, Y, Z)
    bot.entity.position.set(x, Y, Z)
    bot._client.write('vehicle_move', {
      x,
      y: Y,
      z: Z,
      yaw: -90,
      pitch: 0,
      onGround: trial.onGround
    })
    packets++
    batchPackets++
    x += STEP

    if (batchPackets >= trial.batchSize) {
      batchPackets = 0
      await sleep(TICK_MS)
    }
  }

  if (!corrected() && bot.vehicle) {
    bot.vehicle.position.set(targetX, Y, Z)
    bot.entity.position.set(targetX, Y, Z)
    bot._client.write('vehicle_move', {
      x: targetX,
      y: Y,
      z: Z,
      yaw: -90,
      pitch: 0,
      onGround: trial.onGround
    })
    packets++
  }

  return {
    packets,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6
  }
}

function waitForToken (bot, token, timeoutMs = 1300) {
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

async function serverBeyond (bot, boundary, id) {
  const token = `PHASELAB_BURST_${id}_${Date.now()}`
  const seen = waitForToken(bot, token)
  bot.chat(`/execute if entity @s[x=${boundary},y=64,z=-4,dx=4,dy=7,dz=8] run tellraw @s {"text":"${token}"}`)
  return await seen
}

async function dismountSnapshot (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 1800)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await sleep(220)
  const packetPromise = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  await sleep(100)
  return {
    packet: args ? args[0] : null,
    position: {
      x: bot.entity.position.x,
      y: bot.entity.position.y,
      z: bot.entity.position.z
    }
  }
}

async function openWitness (bot, witness) {
  const block = bot.blockAt(witness)
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  }
  const opened = onceWithTimeout(bot, 'windowOpen', 1300)
  try {
    await bot.lookAt(witness.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  if (!await opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

function plans () {
  return [
    {
      course: { kind: 'solid', thickness: 240 },
      trials: [
        [10, true], [10, false], [8, true], [8, false],
        [12, true], [16, true], [20, true], [5, true], [4, true], [2, true], [1, true]
      ]
    },
    {
      course: { kind: 'layered', thickness: 16 },
      trials: [[10, true], [8, true], [12, true], [16, true], [20, true], [5, true], [4, true]]
    },
    {
      course: { kind: 'layered', thickness: 64 },
      trials: [[10, true], [8, true], [12, true], [16, true], [20, true], [5, true]]
    }
  ]
}

async function runTrial (bot, course, trial, id) {
  await reset(bot)
  const boat = await mountBoat(bot)
  const capture = captureCorrections(bot, boat.id)
  const sent = await sendBatches(bot, course.targetX, trial, () => capture.events.length > 0)
  await sleep(650)
  capture.stop()

  const beyondMounted = await serverBeyond(bot, course.boundaryX, id)
  const snapshot = await dismountSnapshot(bot)
  const beyondPost = snapshot.position.x > course.boundaryX
  const witness = beyondPost
    ? await openWitness(bot, course.witness)
    : { opened: false, reason: 'post_dismount_not_beyond' }

  return {
    course,
    trial,
    packets: sent.packets,
    sendMs: sent.elapsedMs,
    corrections: capture.events,
    beyondMounted,
    snapshot,
    beyondPost,
    witness,
    verified: beyondMounted && beyondPost && witness.opened
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-burst-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      step: STEP,
      tickMs: TICK_MS,
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['kind,thickness,batch_size,on_ground,packets,send_ms,corrections,first_type,first_ms,beyond_mounted,post_x,post_y,post_z,beyond_post,witness,verified']
  for (const r of results) {
    const first = r.corrections[0]
    rows.push([
      r.course.kind,
      r.course.thickness,
      r.trial.batchSize,
      r.trial.onGround,
      r.packets,
      r.sendMs.toFixed(3),
      r.corrections.length,
      first ? first.type : '',
      first ? first.elapsedMs.toFixed(3) : '',
      r.beyondMounted,
      r.snapshot.position.x.toFixed(6),
      r.snapshot.position.y.toFixed(6),
      r.snapshot.position.z.toFixed(6),
      r.beyondPost,
      r.witness.opened,
      r.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-burst-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab burst matrix complete')
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
  bot.on('kicked', reason => console.error('[VehicleBurst kicked]', reason))
  bot.on('error', error => console.error('[VehicleBurst error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Burst bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setupBase(bot)

    const results = []
    let id = 0
    for (const group of plans()) {
      const course = await buildCourse(bot, group.course)
      for (const [batchSize, onGround] of group.trials) {
        const trial = { batchSize, onGround }
        const result = await runTrial(bot, course, trial, id++)
        results.push(result)
        writeReport(results, bot)
        const first = result.corrections[0]
        console.log(
          `[VehicleBurst] ${course.kind}/${course.thickness}` +
          ` batch=${batchSize} ground=${onGround}` +
          ` packets=${result.packets} send=${result.sendMs.toFixed(1)}ms` +
          ` corrections=${result.corrections.length}` +
          (first ? ` first=${first.type}@${first.elapsedMs.toFixed(1)}ms` : '') +
          ` mounted=${result.beyondMounted}` +
          ` postX=${result.snapshot.position.x.toFixed(3)}` +
          ` witness=${result.witness.opened} verified=${result.verified}`
        )
      }
    }

    const verified = results.filter(result => result.verified)
    console.log(`[VehicleBurst] completed=${results.length} verified=${verified.length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[VehicleBurst fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
