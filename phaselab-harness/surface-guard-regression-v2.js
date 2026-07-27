'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
fs.mkdirSync(OUTPUT_DIR, { recursive: true })

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

async function teleport (bot, x, y = 65, z = 0.5) {
  const packet = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s ${x} ${y} ${z}`)
  await packet
  await sleep(180)
}

async function snapshot (bot) {
  const linePromise = waitForPrefix(bot, 'SURFACE_SNAPSHOT ', 2500)
  bot.chat('/surfaceguard snapshot')
  const line = await linePromise
  if (!line) return { ok: false, line: null }
  const match = line.match(/player=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?) health=(-?\d+(?:\.\d+)?) vehicle=(.+?) protected=(true|false) collision=(true|false) quarantine=(-?\d+)/)
  if (!match) return { ok: false, line }
  return {
    ok: true,
    line,
    position: { x: Number(match[1]), y: Number(match[2]), z: Number(match[3]) },
    health: Number(match[4]),
    vehicle: match[5],
    protected: match[6] === 'true',
    collision: match[7] === 'true',
    quarantine: Number(match[8])
  }
}

async function resetEnemy (bot, x = -2.5) {
  bot.chat('/ride @s dismount')
  await sleep(120)
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 120)
  await command(bot, '/surfaceguard reset', 80)
  await command(bot, `/surfaceguard relation ${USERNAME} enemy`, 80)
  await teleport(bot, x)
}

async function runProbe (bot, name, cause, x, expectedBlocked = true) {
  await resetEnemy(bot)
  const before = await snapshot(bot)
  await command(bot, `/surfaceguard probe ${cause} ${x} 65 0.5`, 350)
  const after = await snapshot(bot)
  const blocked = after.ok && after.position.x < 0 && !after.protected && !after.collision
  return {
    name,
    kind: 'teleport',
    expectedBlocked,
    before,
    after,
    passed: expectedBlocked ? blocked : after.ok && after.protected
  }
}

async function runAllowedControl (bot, truce) {
  await resetEnemy(bot)
  if (truce) await command(bot, `/surfaceguard relation ${USERNAME} truce`, 80)
  else await command(bot, `/surfaceguard allow ${USERNAME} 20`, 60)
  await command(bot, '/surfaceguard probe pearl 1.5 65 0.5', 250)
  const after = await snapshot(bot)
  return {
    name: truce ? 'truce_control' : 'temporary_allow_control',
    kind: 'control',
    expectedBlocked: false,
    after,
    passed: after.ok && after.protected && after.position.x >= 1.0 && !after.collision
  }
}

async function mountBoat (bot, x) {
  await command(bot, `/summon minecraft:oak_boat ${x} 65 0.5 {Rotation:[-90f,0f],Invulnerable:1b}`, 180)
  const mounted = onceWithTimeout(bot, 'mount', 1800)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  await sleep(180)
  return bot.vehicle || Object.values(bot.entities).find(entity => entity.name === 'oak_boat') || null
}

function vehicleMove (bot, boat, x) {
  if (boat) boat.position.set(x, 65, 0.5)
  bot._client.write('vehicle_move', {
    x, y: 65, z: 0.5, yaw: -90, pitch: 0, onGround: true
  })
}

async function runMountedRegression (bot) {
  await resetEnemy(bot, -1.25)
  const boat = await mountBoat(bot, -0.8)
  const before = await snapshot(bot)
  for (const x of [-0.55, -0.30, -0.05, 0.20, 0.45, 0.70, 0.95, 1.20]) {
    vehicleMove(bot, boat, x)
    await sleep(50)
  }
  await sleep(700)
  const afterRollback = await snapshot(bot)
  for (let i = 0; i < 40; i++) {
    vehicleMove(bot, boat, 1.45 + i * 0.25)
    if ((i + 1) % 10 === 0) await sleep(50)
  }
  await sleep(900)
  const afterStaleFlood = await snapshot(bot)
  return {
    name: 'mounted_crossing_and_stale_handoff',
    kind: 'vehicle',
    before,
    afterRollback,
    afterStaleFlood,
    passed: Boolean(boat)
      && afterRollback.ok && afterRollback.position.x < 0 && !afterRollback.protected
      && afterStaleFlood.ok && afterStaleFlood.position.x < 0
      && !afterStaleFlood.protected && !afterStaleFlood.collision
  }
}

async function buildDismountCage (bot) {
  await command(bot, '/fill -8 64 -4 4 64 4 minecraft:stone')
  await command(bot, '/fill -8 65 -4 4 70 4 minecraft:air')
  // The player anchor remains at X=-4.5 in open air. Only the region around the
  // remotely mounted boundary boat is caged.
  await command(bot, '/fill -2 65 -1 -1 67 1 minecraft:obsidian')
  await command(bot, '/fill -1 65 -2 0 67 -1 minecraft:obsidian')
  await command(bot, '/fill -1 65 2 0 67 2 minecraft:obsidian')
  await command(bot, '/fill -1 68 -1 0 68 1 minecraft:obsidian')
}

async function runDismountRegression (bot, boatX) {
  await resetEnemy(bot, -4.5)
  await buildDismountCage(bot)
  const safeAnchor = await snapshot(bot)
  const boat = await mountBoat(bot, boatX)
  const mounted = await snapshot(bot)
  for (let frame = 0; frame < 10; frame++) {
    bot._client.write('player_input', { inputs: { shift: true } })
    bot._client.write('tick_end', {})
    await sleep(50)
  }
  bot._client.write('player_input', { inputs: {} })
  bot._client.write('tick_end', {})
  await sleep(800)
  const after = await snapshot(bot)
  return {
    name: `dismount_boundary_${boatX}`,
    kind: 'dismount',
    boatX,
    safeAnchor,
    mounted,
    after,
    passed: Boolean(boat) && safeAnchor.ok && !safeAnchor.collision
      && after.ok && after.position.x <= -4.0 && !after.protected
      && !after.collision && after.vehicle === 'none'
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'surface-guard-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      count: results.length,
      passed: results.filter(result => result.passed).length
    },
    results
  }, null, 2))
  const rows = ['name,kind,passed,expected_blocked,after_x,after_protected,after_collision,after_vehicle']
  for (const result of results) {
    const after = result.after || result.afterStaleFlood || result.afterRollback || {}
    rows.push([
      result.name, result.kind, result.passed, result.expectedBlocked ?? '',
      after.position?.x?.toFixed(6) ?? '', after.protected ?? '',
      after.collision ?? '', String(after.vehicle ?? '').replaceAll(',', ';')
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'surface-guard-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try { if (bot && bot._client && !bot._client.ended) bot.quit('SurfaceGuard v2 complete') } catch (_) {}
  await sleep(250)
  process.exit(code)
}

async function main () {
  const bot = mineflayer.createBot({
    host: HOST, port: PORT, username: USERNAME, auth: 'offline',
    version: '1.21.11', physicsEnabled: false, hideErrors: false
  })
  bot.on('kicked', reason => console.error('[SurfaceGuardV2 kicked]', reason))
  bot.on('error', error => console.error('[SurfaceGuardV2 error]', error))
  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await command(bot, `/gamemode survival ${USERNAME}`)
    await command(bot, '/gamerule doDaylightCycle false')
    await command(bot, '/time set day')
    await command(bot, '/fill -16 64 -8 40 64 8 minecraft:stone')
    await command(bot, '/fill -16 65 -8 40 72 8 minecraft:air')
    await command(bot, '/surfaceguard zone 0 32')

    const results = []
    for (const [name, cause] of [
      ['pearl_claim_crossing', 'pearl'],
      ['chorus_claim_crossing', 'chorus'],
      ['nether_claim_crossing', 'nether'],
      ['end_claim_crossing', 'end']
    ]) {
      results.push(await runProbe(bot, name, cause, 1.5, true))
      writeReport(results, bot)
    }

    await command(bot, '/setblock -4 65 0 minecraft:obsidian')
    results.push(await runProbe(bot, 'pearl_solid_overlap', 'pearl', -3.5, true))
    writeReport(results, bot)

    results.push(await runAllowedControl(bot, false))
    writeReport(results, bot)
    results.push(await runAllowedControl(bot, true))
    writeReport(results, bot)
    results.push(await runMountedRegression(bot))
    writeReport(results, bot)

    for (const x of [-0.80, -0.55, -0.30, -0.05]) {
      results.push(await runDismountRegression(bot, x))
      writeReport(results, bot)
    }

    const failed = results.filter(result => !result.passed)
    console.log(`[SurfaceGuardV2] completed=${results.length} passed=${results.length - failed.length} failed=${failed.length}`)
    if (failed.length) console.error('[SurfaceGuardV2] failed', failed.map(result => result.name))
    await shutdown(bot, failed.length === 0 ? 0 : 1)
  } catch (error) {
    console.error('[SurfaceGuardV2 fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
