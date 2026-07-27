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

async function baseSetup (bot) {
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
  const end = course.thickness
  if (course.kind === 'solid') {
    await command(bot, `/fill 1 65 -3 ${end} 69 3 minecraft:obsidian`, Math.min(1200, 150 + end * 3))
  } else if (course.kind === 'layered') {
    for (let x = 1; x <= end; x++) {
      const block = x % 2 === 1 ? 'minecraft:obsidian' : 'minecraft:water'
      await command(bot, `/fill ${x} 65 -3 ${x} 69 3 ${block}`, 60)
    }
  } else {
    throw new Error(`Unknown course kind ${course.kind}`)
  }
  const witnessX = end + 3
  await command(bot, `/setblock ${witnessX} 65 0 minecraft:barrel[facing=west]`, 180)
  return { wallEnd: end, targetX: end + 0.72, witness: new Vec3(witnessX, 65, 0) }
}

async function reset (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 1600)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 120)
  const packetPromise = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s -1.25 ${Y} ${Z}`)
  if (!await packetPromise) throw new Error('Reset teleport packet missing')
  await sleep(120)
}

async function spawnAndRide (bot) {
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
  if (!bot.vehicle) throw new Error('Ride fixture failed')
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
  const vehicle = packet => add('vehicle_move', packet)
  const player = packet => add('player_position', packet)
  const teleport = packet => {
    if (packet.entityId === boatId) add('boat_entity_teleport', packet)
  }
  bot._client.on('vehicle_move', vehicle)
  bot._client.on('position', player)
  bot._client.on('entity_teleport', teleport)
  return {
    events,
    stop () {
      bot._client.removeListener('vehicle_move', vehicle)
      bot._client.removeListener('position', player)
      bot._client.removeListener('entity_teleport', teleport)
    }
  }
}

async function sendSequence (bot, targetX, trial, correctedRef) {
  let packetCount = 0
  let x = START_X + trial.step
  while (x < targetX - 1e-9 && !correctedRef.value && bot.vehicle) {
    bot.vehicle.position.set(x, Y, Z)
    bot.entity.position.set(x, Y, Z)
    bot._client.write('vehicle_move', { x, y: Y, z: Z, yaw: -90, pitch: 0, onGround: trial.onGround })
    packetCount++
    if (trial.delayMs > 0) await sleep(trial.delayMs)
    else if (packetCount % 20 === 0) await new Promise(resolve => setImmediate(resolve))
    x += trial.step
  }
  if (!correctedRef.value && bot.vehicle) {
    bot.vehicle.position.set(targetX, Y, Z)
    bot.entity.position.set(targetX, Y, Z)
    bot._client.write('vehicle_move', { x: targetX, y: Y, z: Z, yaw: -90, pitch: 0, onGround: trial.onGround })
    packetCount++
  }
  return packetCount
}

function waitForToken (bot, token, timeoutMs = 1200) {
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
  const token = `PHASELAB_HARD_${id}_${Date.now()}`
  const seen = waitForToken(bot, token)
  bot.chat(`/execute if entity @s[x=${boundary},y=64,z=-4,dx=4,dy=6,dz=8] run tellraw @s {"text":"${token}"}`)
  return await seen
}

async function witnessOpen (bot, witness) {
  const block = bot.blockAt(witness)
  if (!block || block.name !== 'barrel') return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  const promise = onceWithTimeout(bot, 'windowOpen', 1200)
  try {
    await bot.lookAt(witness.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  const opened = await promise
  if (!opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function dismountSnapshot (bot) {
  if (bot.vehicle) {
    let event = onceWithTimeout(bot, 'dismount', 1500)
    bot.dismount()
    await event
    if (bot.vehicle) {
      event = onceWithTimeout(bot, 'dismount', 1500)
      bot._client.write('player_input', { inputs: { shift: true } })
      await event
      bot._client.write('player_input', { inputs: { shift: false } })
    }
  }
  await sleep(220)
  const packetPromise = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  await sleep(80)
  return {
    packet: args ? args[0] : null,
    position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z }
  }
}

function trialPlan () {
  return [
    { course: { kind: 'solid', thickness: 1 }, variants: [
      [0.249, 50], [0.25, 50], [0.2501, 50], [0.251, 50], [0.26, 50],
      [0.25, 0], [0.25, 5], [0.25, 10], [0.25, 20], [0.25, 25], [0.25, 100]
    ] },
    { course: { kind: 'solid', thickness: 5 }, variants: [
      [0.249, 50], [0.25, 50], [0.2501, 50], [0.251, 50], [0.25, 10], [0.25, 100]
    ] },
    { course: { kind: 'layered', thickness: 16 }, variants: [
      [0.25, 50], [0.25, 10], [0.249, 50], [0.2501, 50]
    ] },
    { course: { kind: 'solid', thickness: 16 }, variants: [
      [0.25, 50], [0.25, 10], [0.25, 5], [0.2501, 50]
    ] },
    { course: { kind: 'solid', thickness: 64 }, variants: [
      [0.25, 50], [0.25, 10]
    ] },
    { course: { kind: 'solid', thickness: 240 }, variants: [
      [0.25, 50], [0.25, 10]
    ] }
  ]
}

async function runTrial (bot, courseInfo, trial, id) {
  await reset(bot)
  const boat = await spawnAndRide(bot)
  const capture = captureCorrections(bot, boat.id)
  const correctedRef = { value: false }
  const mark = () => { correctedRef.value = true }
  bot._client.on('vehicle_move', mark)
  bot._client.on('position', mark)
  bot._client.on('entity_teleport', mark)

  const started = process.hrtime.bigint()
  const packetCount = await sendSequence(bot, courseInfo.targetX, trial, correctedRef)
  const sendElapsedMs = Number(process.hrtime.bigint() - started) / 1e6
  await sleep(650)

  bot._client.removeListener('vehicle_move', mark)
  bot._client.removeListener('position', mark)
  bot._client.removeListener('entity_teleport', mark)
  capture.stop()

  const beyond = await serverBeyond(bot, courseInfo.wallEnd + 0.70, id)
  const witness = beyond ? await witnessOpen(bot, courseInfo.witness) : { opened: false, reason: 'server_not_beyond' }
  const snapshot = await dismountSnapshot(bot)
  const verified = beyond && witness.opened && snapshot.position.x > courseInfo.wallEnd + 0.70

  return {
    trial,
    courseInfo,
    packetCount,
    sendElapsedMs,
    corrections: capture.events,
    beyond,
    witness,
    snapshot,
    verified
  }
}

function writeReports (results, bot) {
  const report = {
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      startX: START_X,
      resultCount: results.length
    },
    results
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-hardening-report.json'), JSON.stringify(report, null, 2))
  const rows = ['kind,thickness,step,delay_ms,on_ground,packets,send_ms,corrections,first_type,first_ms,beyond,witness,post_x,post_y,post_z,verified']
  for (const r of results) {
    const first = r.corrections[0]
    rows.push([
      r.courseInfo.kind, r.courseInfo.wallEnd, r.trial.step, r.trial.delayMs, r.trial.onGround,
      r.packetCount, r.sendElapsedMs.toFixed(3), r.corrections.length,
      first ? first.type : '', first ? first.elapsedMs.toFixed(3) : '',
      r.beyond, r.witness.opened,
      r.snapshot.position.x.toFixed(6), r.snapshot.position.y.toFixed(6), r.snapshot.position.z.toFixed(6),
      r.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'vehicle-hardening-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab vehicle hardening complete')
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
  bot.on('kicked', reason => console.error('[VehicleHardening kicked]', reason))
  bot.on('error', error => console.error('[VehicleHardening error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Hardening bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await baseSetup(bot)

    const results = []
    let id = 0
    for (const group of trialPlan()) {
      const courseInfo = { ...group.course, ...(await buildCourse(bot, group.course)) }
      for (const [step, delayMs] of group.variants) {
        const trial = { step, delayMs, onGround: false }
        const result = await runTrial(bot, courseInfo, trial, id++)
        results.push(result)
        const first = result.corrections[0]
        console.log(
          `[VehicleHardening] ${courseInfo.kind}/${courseInfo.wallEnd} step=${step} delay=${delayMs}` +
          ` packets=${result.packetCount} send=${result.sendElapsedMs.toFixed(1)}ms` +
          ` corrections=${result.corrections.length}` +
          (first ? ` first=${first.type}@${first.elapsedMs.toFixed(1)}ms` : '') +
          ` beyond=${result.beyond} witness=${result.witness.opened}` +
          ` postX=${result.snapshot.position.x.toFixed(3)} verified=${result.verified}`
        )
      }
    }

    writeReports(results, bot)
    const verified = results.filter(r => r.verified)
    console.log(`[VehicleHardening] completed=${results.length} verified=${verified.length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[VehicleHardening fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
