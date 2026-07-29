'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-brewing-cache-xp')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  cycles: [],
  beforeTake: null,
  afterTake: null,
  clickError: null,
  confirmed: false,
  fatal: null
}

function record (type, data = {}) {
  const row = { ts: new Date().toISOString(), type, ...data }
  transcript.push(row)
  console.log(JSON.stringify(row))
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
  bot.on('error', error => record('bot_error', { username, error: String(error.stack || error) }))
  bot.on('kicked', reason => record('kicked', { username, reason: String(reason) }))
  await onceWithTimeout(bot, 'spawn', 45000)
  return bot
}

async function command (bot, text, delay = 400) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 10000) {
  record('command', { username: bot.username, text, expect: String(pattern) })
  return await new Promise((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => finish(new Error(`Timeout waiting for ${pattern}`)), timeoutMs)
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

function parseJson (message) {
  const index = message.indexOf('{')
  if (index < 0) throw new Error(`JSON missing: ${message}`)
  return JSON.parse(message.slice(index))
}

async function cacheState (phaseBot, label) {
  const message = await commandExpect(
    phaseBot,
    `/stacklab alchemystate ${label}`,
    new RegExp(`STACKLAB ALCHEMY STATE ${label} \\{`),
    8000
  )
  return parseJson(message)
}

function slotState (state, slotNumber) {
  for (const stand of state.stands || []) {
    for (const slot of stand.slots || []) {
      if (Number(slot.slot) === slotNumber) return slot
    }
  }
  return null
}

async function openBrewingStand (phaseBot, bot) {
  const windowPromise = onceWithTimeout(bot, 'windowOpen', 20000)
  await commandExpect(
    phaseBot,
    `/stacklab alchemyopen ${bot.username}`,
    /STACKLAB ALCHEMY OPEN player=.* inventory=BREWING/,
    10000
  )
  const [window] = await windowPromise
  await sleep(350)
  if (!String(window.type).includes('brewing')) throw new Error(`Unexpected window ${window.type}`)
  return window
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, attackerBot]

  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    await command(phaseBot, '/stacklab build', 700)
    await command(phaseBot, '/tp AttackerBot 12.5 67 9.5 -90 0', 500)

    // Opening once assigns AuraSkills ownership metadata to this stand.
    let window = await openBrewingStand(phaseBot, attackerBot)
    try { attackerBot.closeWindow(window) } catch (_) {}
    await sleep(350)

    await commandExpect(phaseBot, '/stacklab alchemyprep AttackerBot', /STACKLAB ALCHEMY PREP \{/, 8000)

    for (let cycle = 1; cycle <= 5; cycle++) {
      await command(phaseBot, `/stacklab alchemycycle ${cycle}`, 250)
      await sleep(2500)
      const state = await cacheState(phaseBot, `cycle-${cycle}`)
      report.cycles.push(state)
      record('cycle_state', { cycle, state })
    }

    await command(phaseBot, '/stacklab alchemyfinal', 500)
    window = await openBrewingStand(phaseBot, attackerBot)
    report.beforeTake = await cacheState(phaseBot, 'before-take')

    try {
      await attackerBot.clickWindow(0, 0, 0)
    } catch (error) {
      report.clickError = String(error.stack || error)
    }
    await sleep(900)
    report.afterTake = await cacheState(phaseBot, 'after-take')
    try { attackerBot.closeWindow(window) } catch (_) {}

    const beforeSlot = slotState(report.beforeTake, 0)
    const afterSlot = slotState(report.afterTake, 0)
    const xpGain = Number(report.afterTake.alchemy_xp) - Number(report.beforeTake.alchemy_xp)
    report.analysis = {
      observedBrewEvents: Number(report.beforeTake.observed_brew_events),
      cachedIngredientsBefore: beforeSlot ? Number(beforeSlot.ingredient_count) : -1,
      brewedBefore: beforeSlot ? Boolean(beforeSlot.brewed) : false,
      cachedIngredientsAfter: afterSlot ? Number(afterSlot.ingredient_count) : 0,
      xpBefore: Number(report.beforeTake.alchemy_xp),
      xpAfter: Number(report.afterTake.alchemy_xp),
      xpGain,
      levelBefore: Number(report.beforeTake.alchemy_level),
      levelAfter: Number(report.afterTake.alchemy_level)
    }
    report.confirmed = report.analysis.observedBrewEvents === 5 &&
      report.analysis.cachedIngredientsBefore === 5 &&
      report.analysis.brewedBefore &&
      report.analysis.xpGain === 50 &&
      report.analysis.cachedIngredientsAfter === 0
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'brewing-cache-xp-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'brewing-cache-xp-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab brewing cache XP complete') } catch (_) {}
    }
  }
  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'brewing-cache-xp-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})