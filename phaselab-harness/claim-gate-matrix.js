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
const CLAIM_MIN = 0
const CLAIM_MAX = 15.999
const TARGET_X = 16.72
const STEP = 0.25
const TICK_MS = 50
const WITNESS = new Vec3(19, 65, 0)

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

async function command (bot, text, delay = 120) {
  bot.chat(text)
  await sleep(delay)
}

async function setup (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, '/fill -5 63 -5 24 72 5 minecraft:air', 350)
  await command(bot, '/fill -5 64 -5 24 64 5 minecraft:stone', 350)
  await command(bot, '/fill 0 65 -3 15 69 3 minecraft:obsidian', 700)
  for (let x = 1; x <= 15; x += 2) {
    await command(bot, `/fill ${x} 65 -3 ${x} 69 3 minecraft:water`, 35)
  }
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 180)
  await command(bot, `/claimlab zone ${CLAIM_MIN} ${CLAIM_MAX}`)
}

async function reset (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 1500)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 120)
  const position = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s ${RESET_X} ${Y} ${Z}`)
  if (!await position) throw new Error('Reset teleport packet missing')
  await command(bot, '/claimlab reset', 80)
  await sleep(120)
}

async function setGate (bot, mode, relation) {
  await command(bot, `/claimlab mode ${mode}`)
  await command(bot, `/claimlab relation ${USERNAME} ${relation}`)
}

async function summonAndMount (bot, x = BOAT_X) {
  bot.chat(`/summon minecraft:oak_boat ${x} ${Y} ${Z} {Rotation:[-90f,0f],Invulnerable:1b}`)
  await sleep(180)
  let mounted = onceWithTimeout(bot, 'mount', 1800)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  if (!bot.vehicle) {
    mounted = onceWithTimeout(bot, 'mount', 900)
    bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
    await mounted
  }
  await sleep(100)
  return bot.vehicle || null
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

async function sendBatches (bot, batchSize, corrected) {
  let x = BOAT_X + STEP
  let packets = 0
  let inBatch = 0
  const started = process.hrtime.bigint()
  while (x < TARGET_X - 1e-9 && !corrected() && bot.vehicle) {
    bot.vehicle.position.set(x, Y, Z)
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
    inBatch++
    x += STEP
    if (inBatch >= batchSize) {
      inBatch = 0
      await sleep(TICK_MS)
    }
  }
  if (!corrected() && bot.vehicle) {
    bot.vehicle.position.set(TARGET_X, Y, Z)
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
  }
  return {
    packets,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6
  }
}

function waitForToken (bot, token, timeoutMs = 1400) {
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

async function serverBeyond (bot, id) {
  const token = `CLAIMGATE_${id}_${Date.now()}`
  const seen = waitForToken(bot, token)
  bot.chat(`/execute if entity @s[x=16.70,y=64,z=-4,dx=5,dy=7,dz=8] run tellraw @s {"text":"${token}"}`)
  return await seen
}

async function authoritativeSnapshot (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 1500)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await sleep(180)
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

async function openWitness (bot) {
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 120)
  let block = bot.blockAt(WITNESS)
  for (let attempt = 0; attempt < 20 && (!block || block.name !== 'barrel'); attempt++) {
    await sleep(100)
    block = bot.blockAt(WITNESS)
  }
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
  if (!await opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function crossingTrial (bot, plan, id) {
  await reset(bot)
  await setGate(bot, plan.mode, plan.relation)
  const boat = await summonAndMount(bot)
  if (!boat) {
    return {
      ...plan,
      kind: 'crossing',
      mountedInitially: false,
      packets: 0,
      sendMs: 0,
      corrections: [],
      beyondMounted: false,
      snapshot: { position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z } },
      beyondPost: false,
      witness: { opened: false, reason: 'mount_failed_outside' },
      verified: false
    }
  }

  const capture = captureCorrections(bot, boat.id)
  const sent = await sendBatches(bot, plan.batchSize, () => capture.events.length > 0)
  await sleep(700)
  capture.stop()
  const beyondMounted = await serverBeyond(bot, id)
  const stillMounted = Boolean(bot.vehicle)
  const snapshot = await authoritativeSnapshot(bot)
  const beyondPost = snapshot.position.x > 16.70
  const witness = beyondPost ? await openWitness(bot) : { opened: false, reason: 'not_beyond' }
  return {
    ...plan,
    kind: 'crossing',
    mountedInitially: true,
    stillMountedAfter: stillMounted,
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

async function mountInsideTrial (bot, plan) {
  await reset(bot)
  await setGate(bot, plan.mode, plan.relation)
  const boat = await summonAndMount(bot, 1.50)
  return {
    ...plan,
    kind: 'mount_inside',
    mounted: Boolean(boat),
    playerX: bot.entity.position.x,
    boatX: boat ? boat.position.x : 1.50
  }
}

function expectedPass (result) {
  if (result.kind === 'mount_inside') {
    return result.relation === 'truce' ? result.mounted : !result.mounted
  }
  if (result.mode === 'observe') return result.verified
  if (result.relation === 'truce') return result.verified
  return !result.verified && !result.beyondPost
}

function writeReport (results, bot) {
  const withExpectations = results.map(result => ({
    ...result,
    expectationPassed: expectedPass(result)
  }))
  fs.writeFileSync(path.join(OUTPUT_DIR, 'claim-gate-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      claim: [CLAIM_MIN, CLAIM_MAX],
      step: STEP,
      count: results.length
    },
    results: withExpectations
  }, null, 2))

  const rows = ['kind,mode,relation,batch,mounted_initially,still_mounted,packets,send_ms,corrections,beyond_mounted,post_x,beyond_post,witness,verified,mounted_inside,expectation_passed']
  for (const result of withExpectations) {
    rows.push([
      result.kind,
      result.mode,
      result.relation,
      result.batchSize || '',
      result.mountedInitially ?? '',
      result.stillMountedAfter ?? '',
      result.packets ?? '',
      result.sendMs == null ? '' : result.sendMs.toFixed(3),
      result.corrections ? result.corrections.length : '',
      result.beyondMounted ?? '',
      result.snapshot ? result.snapshot.position.x.toFixed(6) : '',
      result.beyondPost ?? '',
      result.witness ? result.witness.opened : '',
      result.verified ?? '',
      result.mounted ?? '',
      result.expectationPassed
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'claim-gate-report.csv'), `${rows.join('\n')}\n`)
  return withExpectations
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab claim gate matrix complete')
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
  bot.on('kicked', reason => console.error('[ClaimGate kicked]', reason))
  bot.on('error', error => console.error('[ClaimGate error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('ClaimGate bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setup(bot)

    const plans = [
      { mode: 'observe', relation: 'enemy', batchSize: 10 },
      { mode: 'likely', relation: 'enemy', batchSize: 10 },
      { mode: 'strict', relation: 'enemy', batchSize: 10 },
      { mode: 'strict', relation: 'truce', batchSize: 10 },
      { mode: 'likely', relation: 'enemy', batchSize: 100 },
      { mode: 'strict', relation: 'enemy', batchSize: 100 },
      { mode: 'strict', relation: 'truce', batchSize: 20 }
    ]

    const results = []
    let id = 0
    for (const plan of plans) {
      const result = await crossingTrial(bot, plan, id++)
      results.push(result)
      writeReport(results, bot)
      console.log(`[ClaimGate] crossing mode=${plan.mode} relation=${plan.relation}` +
        ` batch=${plan.batchSize} verified=${result.verified}` +
        ` postX=${result.snapshot.position.x.toFixed(3)}` +
        ` corrections=${result.corrections.length}`)
    }

    for (const plan of [
      { mode: 'strict', relation: 'enemy' },
      { mode: 'strict', relation: 'truce' }
    ]) {
      const result = await mountInsideTrial(bot, plan)
      results.push(result)
      writeReport(results, bot)
      console.log(`[ClaimGate] mount mode=${plan.mode} relation=${plan.relation} mounted=${result.mounted}`)
    }

    const finalResults = writeReport(results, bot)
    const failures = finalResults.filter(result => !result.expectationPassed)
    console.log(`[ClaimGate] completed=${finalResults.length} expectationFailures=${failures.length}`)
    await shutdown(bot, failures.length === 0 ? 0 : 2)
  } catch (error) {
    console.error('[ClaimGate fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
