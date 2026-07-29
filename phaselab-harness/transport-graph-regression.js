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
  bot.chat('/ride @s dismount')
  await sleep(120)
  for (const type of ['horse', 'pig', 'camel', 'strider', 'minecart', 'oak_chest_boat']) {
    await command(bot, `/kill @e[type=minecraft:${type}]`, 40)
  }
  await command(bot, '/transportguard reset', 60)
  await teleport(bot, -4.5)
}

async function summonAndMount (bot, spec) {
  await command(bot, `/summon minecraft:${spec.type} -0.8 65 0.5 ${spec.nbt || ''}`, 180)
  const mounted = onceWithTimeout(bot, 'mount', 1800)
  bot.chat(`/ride @s mount @e[type=minecraft:${spec.type},limit=1,sort=nearest]`)
  await mounted
  await sleep(200)
  return snapshot(bot)
}

async function runBlocked (bot, spec) {
  await reset(bot)
  const before = await summonAndMount(bot, spec)
  await command(bot, '/transportguard probe 1.5 65 0.5', 450)
  const after = await snapshot(bot)
  return {
    name: `blocked_${spec.name}`,
    entity: spec.type,
    expectedBlocked: true,
    before,
    after,
    passed: before.ok && before.mounted && after.ok
      && after.player.x < 0 && after.root.x < 0 && !after.protected
  }
}

async function runAllowed (bot, spec) {
  await reset(bot)
  const before = await summonAndMount(bot, spec)
  await command(bot, `/transportguard allow ${USERNAME} 20`, 60)
  await command(bot, '/transportguard probe 1.5 65 0.5', 450)
  const after = await snapshot(bot)
  return {
    name: `allowed_${spec.name}`,
    entity: spec.type,
    expectedBlocked: false,
    before,
    after,
    passed: before.ok && before.mounted && after.ok && after.root.x >= 1.0
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
  const rows = ['name,entity,expected_blocked,passed,before_mounted,after_player_x,after_root_x,after_root_type,after_mounted,after_protected']
  for (const result of results) {
    rows.push([
      result.name, result.entity, result.expectedBlocked, result.passed,
      result.before?.mounted ?? '', result.after?.player?.x?.toFixed(6) ?? '',
      result.after?.root?.x?.toFixed(6) ?? '', result.after?.rootType ?? '',
      result.after?.mounted ?? '', result.after?.protected ?? ''
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'transport-graph-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try { if (bot && bot._client && !bot._client.ended) bot.quit('Transport graph complete') } catch (_) {}
  await sleep(250)
  process.exit(code)
}

async function main () {
  const bot = mineflayer.createBot({
    host: HOST, port: PORT, username: USERNAME, auth: 'offline',
    version: '1.21.11', physicsEnabled: false, hideErrors: false
  })
  bot.on('kicked', reason => console.error('[TransportGraph kicked]', reason))
  bot.on('error', error => console.error('[TransportGraph error]', error))

  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await command(bot, `/gamemode survival ${USERNAME}`)
    await command(bot, '/fill -16 64 -8 40 64 8 minecraft:stone')
    await command(bot, '/fill -16 65 -8 40 72 8 minecraft:air')
    await command(bot, '/transportguard zone 0 32')

    const specs = [
      { name: 'horse', type: 'horse', nbt: '{Tame:1b}' },
      { name: 'pig', type: 'pig' },
      { name: 'camel', type: 'camel', nbt: '{Tame:1b}' },
      { name: 'strider', type: 'strider' },
      { name: 'minecart', type: 'minecart' },
      { name: 'chest_boat', type: 'oak_chest_boat' }
    ]

    const results = []
    for (const spec of specs) {
      const result = await runBlocked(bot, spec)
      results.push(result)
      writeReport(results, bot)
      console.log(`[TransportGraph] ${result.name} passed=${result.passed}`)
    }
    for (const spec of [specs[0], specs[4], specs[5]]) {
      const result = await runAllowed(bot, spec)
      results.push(result)
      writeReport(results, bot)
      console.log(`[TransportGraph] ${result.name} passed=${result.passed}`)
    }

    const failed = results.filter(result => !result.passed)
    console.log(`[TransportGraph] completed=${results.length} passed=${results.length - failed.length} failed=${failed.length}`)
    if (failed.length) console.error('[TransportGraph] failed', failed.map(result => result.name))
    await shutdown(bot, failed.length === 0 ? 0 : 1)
  } catch (error) {
    console.error('[TransportGraph fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
