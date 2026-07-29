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
    function finish(value) {
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

async function teleport (bot, x) {
  const packet = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s ${x} 65 0.5`)
  await packet
  await sleep(180)
}

async function snapshot (bot) {
  const linePromise = waitForPrefix(bot, 'TRANSPORT_SNAPSHOT ', 2500)
  bot.chat('/transportguard snapshot')
  const line = await linePromise
  if (!line) return { ok: false, line: null }
  const match = line.match(/player=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?) root=([^@]+)@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?) protected=(true|false) mounted=(true|false)/)
  if (!match) return { ok: false, line }
  return {
    ok: true,
    line,
    player: { x: Number(match[1]), y: Number(match[2]), z: Number(match[3]) },
    rootType: match[4],
    root: { x: Number(match[5]), y: Number(match[6]), z: Number(match[7]) },
    protected: match[8] === 'true',
    mounted: match[9] === 'true'
  }
}

async function reset (bot) {
  await command(bot, '/transportfixture clear', 100)
  await command(bot, '/transportguard reset', 60)
  await teleport(bot, -4.5)
}

async function mountFixture (bot, type) {
  await command(bot, `/transportfixture mount ${type}`, 250)
  return snapshot(bot)
}

async function runBlocked (bot, type) {
  await reset(bot)
  const before = await mountFixture(bot, type)
  await command(bot, '/transportguard probe 1.5 65 0.5', 500)
  const after = await snapshot(bot)
  return {
    name: `blocked_${type}`,
    type,
    expectedBlocked: true,
    before,
    after,
    passed: before.ok && before.mounted && after.ok
      && after.player.x < 0 && after.root.x < 0 && !after.protected
  }
}

async function runAllowed (bot, type) {
  await reset(bot)
  const before = await mountFixture(bot, type)
  await command(bot, `/transportguard allow ${USERNAME} 20`, 60)
  await command(bot, '/transportguard probe 1.5 65 0.5', 500)
  const after = await snapshot(bot)
  return {
    name: `allowed_${type}`,
    type,
    expectedBlocked: false,
    before,
    after,
    passed: before.ok && before.mounted && after.ok
      && after.player.x >= 1.0 && after.root.x >= 1.0
      && after.protected && after.mounted
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'transport-graph-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      count: results.length,
      passed: results.filter(result => result.passed).length
    },
    results
  }, null, 2))
  const rows = ['name,type,expected_blocked,passed,before_mounted,before_root,after_player_x,after_root_x,after_root,after_mounted,after_protected']
  for (const result of results) {
    rows.push([
      result.name, result.type, result.expectedBlocked, result.passed,
      result.before?.mounted ?? '', result.before?.rootType ?? '',
      result.after?.player?.x?.toFixed(6) ?? '', result.after?.root?.x?.toFixed(6) ?? '',
      result.after?.rootType ?? '', result.after?.mounted ?? '', result.after?.protected ?? ''
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'transport-graph-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try { if (bot && bot._client && !bot._client.ended) bot.quit('Transport graph v2 complete') } catch (_) {}
  await sleep(250)
  process.exit(code)
}

async function main () {
  const bot = mineflayer.createBot({
    host: HOST, port: PORT, username: USERNAME, auth: 'offline',
    version: '1.21.11', physicsEnabled: false, hideErrors: false
  })
  bot.on('kicked', reason => console.error('[TransportGraphV2 kicked]', reason))
  bot.on('error', error => console.error('[TransportGraphV2 error]', error))
  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await command(bot, `/gamemode survival ${USERNAME}`)
    await command(bot, '/fill -16 64 -8 40 64 8 minecraft:stone')
    await command(bot, '/fill -16 65 -8 40 72 8 minecraft:air')
    await command(bot, '/transportguard zone 0 32')

    const types = ['horse', 'pig', 'camel', 'strider', 'minecart', 'chest_boat']
    const results = []
    for (const type of types) {
      results.push(await runBlocked(bot, type))
      writeReport(results, bot)
    }
    for (const type of types) {
      results.push(await runAllowed(bot, type))
      writeReport(results, bot)
    }

    const failed = results.filter(result => !result.passed)
    console.log(`[TransportGraphV2] completed=${results.length} passed=${results.length - failed.length} failed=${failed.length}`)
    if (failed.length) console.error('[TransportGraphV2] failed', failed.map(result => result.name))
    await shutdown(bot, failed.length === 0 ? 0 : 1)
  } catch (error) {
    console.error('[TransportGraphV2 fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
