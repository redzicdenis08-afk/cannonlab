'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-falling-web-xp')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  modes: {},
  confirmed: false,
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
  return bot
}

async function command (bot, text, delay = 450) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 12000) {
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

function parseJsonMessage (message) {
  const start = message.indexOf('{')
  if (start < 0) throw new Error(`JSON missing from message: ${message}`)
  return JSON.parse(message.slice(start))
}

async function snapshot (phaseBot, label) {
  const message = await commandExpect(
    phaseBot,
    `/stacklab weblaundersnapshot ${label}`,
    new RegExp(`STACKLAB WEB SNAPSHOT ${label} \\{`),
    10000
  )
  const value = parseJsonMessage(message)
  record('snapshot', value)
  return value
}

async function waitFor (phaseBot, labelPrefix, predicate, timeoutMs = 30000, intervalMs = 500) {
  const deadline = Date.now() + timeoutMs
  let index = 0
  let last = null
  while (Date.now() < deadline) {
    last = await snapshot(phaseBot, `${labelPrefix}-${index++}`)
    if (predicate(last)) return last
    await sleep(intervalMs)
  }
  throw new Error(`Timeout in ${labelPrefix}; last=${JSON.stringify(last)}`)
}

async function waitForInventoryItem (bot, name, timeoutMs = 7000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const item = bot.inventory.items().find(entry => entry.name === name)
    if (item) return item
    await sleep(150)
  }
  return null
}

async function placeGravel (phaseBot) {
  const message = await commandExpect(
    phaseBot,
    '/stacklab weblaunderplace AttackerBot',
    /STACKLAB WEB PLACE \{/,
    12000
  )
  const evidence = parseJsonMessage(message)
  if (!evidence.invoked) throw new Error(`Server placement failed: ${JSON.stringify(evidence)}`)
  await sleep(500)
  return evidence
}

async function runCycle (phaseBot, attackerBot, mode, cycle) {
  if (cycle > 1) {
    await commandExpect(
      phaseBot,
      `/stacklab weblaunderreset AttackerBot ${mode}`,
      /STACKLAB WEB RESET \{/,
      10000
    )
    await sleep(600)
  }

  const before = await snapshot(phaseBot, `${mode}-${cycle}-before`)
  const placement = await placeGravel(phaseBot)
  const placed = await waitFor(
    phaseBot,
    `${mode}-${cycle}-placed`,
    value => value.top_type === 'GRAVEL' && value.top_placed === true,
    12000,
    350
  )

  if (Number(placed.total_gravel) !== 1) {
    throw new Error(`Gravel conservation failed after placement: ${JSON.stringify(placed)}`)
  }

  await commandExpect(phaseBot, '/stacklab weblaunderdrop', /STACKLAB WEB DROP \{/, 10000)

  let webWitness = null
  if (mode === 'web') {
    webWitness = await waitFor(
      phaseBot,
      `${mode}-${cycle}-in-web`,
      value => value.falling_in_web === true,
      30000,
      400
    )
    await sleep(1200)
    await commandExpect(phaseBot, '/stacklab weblaunderrelease', /STACKLAB WEB RELEASE \{/, 10000)
  }

  const landed = await waitFor(
    phaseBot,
    `${mode}-${cycle}-landed`,
    value => value.landing_type === 'GRAVEL' && Number(value.falling_gravel) === 0,
    30000,
    500
  )

  await command(phaseBot, '/tp AttackerBot 31.25 65 0.5 -90 0', 450)
  const breakMessage = await commandExpect(
    phaseBot,
    '/stacklab weblaunderbreak AttackerBot',
    /STACKLAB WEB BREAK \{/,
    10000
  )
  const breakEvidence = parseJsonMessage(breakMessage)
  await sleep(1800)
  const after = await waitFor(
    phaseBot,
    `${mode}-${cycle}-after`,
    value => value.landing_type === 'AIR' && Number(value.inventory_gravel) >= 1 && Number(value.dropped_gravel) === 0,
    10000,
    400
  )

  const xpBefore = Number(before.excavation_xp)
  const xpAfter = Number(after.excavation_xp)
  const xpGain = xpAfter - xpBefore
  const gravelGain = Number(after.total_gravel) - Number(before.total_gravel)
  const preBreakConserved = Number(placed.total_gravel) === Number(before.total_gravel) &&
    Number(landed.total_gravel) === Number(before.total_gravel)
  const result = {
    cycle,
    before,
    placement,
    placed,
    webWitness,
    landed,
    breakEvidence,
    after,
    xpGain,
    gravelGain,
    markerLost: placed.top_placed === true && landed.landing_placed === false,
    markerPreserved: placed.top_placed === true && landed.landing_placed === true,
    preBreakConserved
  }
  record('cycle_result', { mode, ...result })
  return result
}

async function runMode (phaseBot, attackerBot, mode, cycles) {
  await commandExpect(
    phaseBot,
    `/stacklab weblaunderbuild AttackerBot ${mode}`,
    /STACKLAB WEB BUILD \{/,
    12000
  )
  await sleep(900)
  const results = []
  for (let cycle = 1; cycle <= cycles; cycle++) {
    results.push(await runCycle(phaseBot, attackerBot, mode, cycle))
  }
  return {
    mode,
    cycles: results,
    totalXpGain: results.reduce((sum, entry) => sum + entry.xpGain, 0),
    totalGravelGain: results.reduce((sum, entry) => sum + entry.gravelGain, 0),
    allPreBreakConserved: results.every(entry => entry.preBreakConserved),
    allMarkerLost: results.every(entry => entry.markerLost),
    allMarkerPreserved: results.every(entry => entry.markerPreserved)
  }
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, attackerBot]
  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival AttackerBot')

    report.modes.web = await runMode(phaseBot, attackerBot, 'web', 3)
    report.modes.control = await runMode(phaseBot, attackerBot, 'control', 2)

    const web = report.modes.web
    const control = report.modes.control
    report.confirmed = Boolean(
      web.allPreBreakConserved &&
      web.allMarkerLost &&
      web.cycles.every(entry => entry.xpGain > 0) &&
      web.totalXpGain > 0 &&
      control.allPreBreakConserved &&
      control.allMarkerPreserved &&
      control.cycles.every(entry => entry.xpGain === 0 && entry.gravelGain === 0)
    )
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'falling-web-xp-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'falling-web-xp-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab falling web XP complete') } catch (_) {}
    }
  }
  if (report.fatal || !report.confirmed) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'falling-web-xp-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
