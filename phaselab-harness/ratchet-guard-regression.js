'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const RESET_X = -1.25
const BOAT_X = -0.80
const Y = 65
const Z = 0.50
const BORDER_TARGET = 0.20
const TARGET_X = 16.72
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

async function command (bot, text, delay = 100) {
  bot.chat(text)
  await sleep(delay)
}

async function serverSnapshot (bot) {
  const linePromise = waitForPrefix(bot, 'COURSE_SNAPSHOT ')
  bot.chat('/courselab snapshot')
  const line = await linePromise
  if (!line) return { ok: false, line: null }
  const match = line.match(/player=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?) health=(-?\d+(?:\.\d+)?) fire=(-?\d+) vehicle=(none|-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?)/)
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
  await command(bot, '/claimlab zone 0 239.999')
  await command(bot, '/courselab build mixed', 2800)
}

async function reset (bot) {
  bot.chat('/ride @s dismount')
  await sleep(180)
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 120)
  bot.vehicle = null
  const positionPromise = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s ${RESET_X} ${Y} ${Z}`)
  if (!await positionPromise) throw new Error('Reset position packet missing')
  await command(bot, '/claimlab reset', 60)
  await command(bot, '/courselab reset', 60)
  await command(bot, '/ratchetguard reset', 60)
  await command(bot, '/claimlab mode likely', 60)
  await command(bot, `/claimlab relation ${USERNAME} enemy`, 60)
}

async function mountBoat (bot) {
  bot.chat(`/summon minecraft:oak_boat ${BOAT_X} ${Y} ${Z} {Rotation:[-90f,0f]}`)
  await sleep(180)
  const mountPromise = onceWithTimeout(bot, 'mount', 1800)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mountPromise
  await sleep(180)
  const snapshot = await serverSnapshot(bot)
  const boat = bot.vehicle || Object.values(bot.entities)
    .find(entity => entity.name === 'oak_boat' || entity.objectType === 'Boat') || null
  return {
    boat,
    serverMounted: snapshot.ok && snapshot.vehicle !== 'none',
    snapshot
  }
}

function writeVehicleMove (bot, boat, x) {
  if (boat && boat.position) boat.position.set(x, Y, Z)
  bot.entity.position.set(x, Y, Z)
  bot._client.write('vehicle_move', {
    x,
    y: Y,
    z: Z,
    yaw: -90,
    pitch: 0,
    onGround: true
  })
}

async function runTrial (bot, batchSize, id) {
  await reset(bot)
  const mount = await mountBoat(bot)
  if (!mount.serverMounted || !mount.boat) {
    return {
      id,
      batchSize,
      serverMounted: mount.serverMounted,
      initialSnapshot: mount.snapshot,
      finalSnapshot: null,
      blocked: false,
      reason: 'server_mount_failed'
    }
  }

  for (const x of [-0.55, -0.30, -0.05]) {
    writeVehicleMove(bot, mount.boat, x)
    await sleep(TICK_MS)
  }
  writeVehicleMove(bot, mount.boat, BORDER_TARGET)
  await sleep(250)

  let x = BORDER_TARGET + STEP
  while (x < TARGET_X - 1e-9) {
    let sent = 0
    while (sent < batchSize && x < TARGET_X - 1e-9) {
      writeVehicleMove(bot, mount.boat, x)
      x += STEP
      sent++
    }
    await sleep(TICK_MS)
  }
  writeVehicleMove(bot, mount.boat, TARGET_X)
  await sleep(650)

  const finalSnapshot = await serverSnapshot(bot)
  const blocked = finalSnapshot.ok
    && finalSnapshot.position.x < 0.0
    && finalSnapshot.vehicle === 'none'

  return {
    id,
    batchSize,
    serverMounted: true,
    initialSnapshot: mount.snapshot,
    finalSnapshot,
    blocked,
    reason: blocked ? 'outside_and_dismounted' : 'inside_or_still_mounted'
  }
}

function writeReport (results, bot) {
  const report = {
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      targetX: TARGET_X
    },
    results
  }
  fs.writeFileSync(
    path.join(OUTPUT_DIR, 'ratchet-guard-regression-report.json'),
    JSON.stringify(report, null, 2)
  )

  const rows = ['id,batch,server_mounted,final_x,final_vehicle,blocked,reason']
  for (const result of results) {
    rows.push([
      result.id,
      result.batchSize,
      result.serverMounted,
      result.finalSnapshot?.position?.x?.toFixed(6) ?? '',
      result.finalSnapshot?.vehicle ?? '',
      result.blocked,
      result.reason
    ].join(','))
  }
  fs.writeFileSync(
    path.join(OUTPUT_DIR, 'ratchet-guard-regression-report.csv'),
    `${rows.join('\n')}\n`
  )
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('Ratchet guard regression complete')
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
  bot.on('kicked', reason => console.error('[RatchetGuardRegression kicked]', reason))
  bot.on('error', error => console.error('[RatchetGuardRegression error]', error))

  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setup(bot)

    const results = []
    for (const batchSize of [8, 10, 16, 20]) {
      const result = await runTrial(bot, batchSize, results.length)
      results.push(result)
      writeReport(results, bot)
      console.log(`[RatchetGuardRegression] batch=${batchSize}` +
        ` finalX=${result.finalSnapshot?.position?.x?.toFixed(2) ?? 'none'}` +
        ` vehicle=${result.finalSnapshot?.vehicle ?? 'unknown'}` +
        ` BLOCKED=${result.blocked}`)
    }

    const passed = results.length === 4 && results.every(result => result.blocked)
    console.log(`[RatchetGuardRegression] completed=${results.length}` +
      ` blocked=${results.filter(result => result.blocked).length}` +
      ` PASSED=${passed}`)
    await shutdown(bot, passed ? 0 : 1)
  } catch (error) {
    console.error('[RatchetGuardRegression fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
