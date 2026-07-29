'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-reward-timing-xp')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  initial: null,
  trials: [],
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
  bot.on('error', error => record('bot_error', { username, error: String(error.stack || error) }))
  bot.on('kicked', reason => record('kicked', { username, reason: String(reason) }))
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
    `/stacklab rewardsnapshot AttackerBot ${label}`,
    new RegExp(`STACKLAB REWARD SNAPSHOT ${label} \\{`),
    10000
  )
  const value = parseJsonMessage(message)
  record('snapshot', value)
  return value
}

async function eatAttempt (attackerBot) {
  const apple = attackerBot.inventory.items().find(item => item.name === 'enchanted_golden_apple')
  if (!apple) throw new Error('Enchanted golden apple is missing before consume attempt')
  await attackerBot.equip(apple, 'hand')
  await sleep(250)
  attackerBot.activateItem()
  await sleep(2300)
  attackerBot.deactivateItem()
  await sleep(450)
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, attackerBot]
  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    const prepMessage = await commandExpect(
      phaseBot,
      '/stacklab rewardprep AttackerBot',
      /STACKLAB REWARD PREP \{/,
      15000
    )
    report.initial = parseJsonMessage(prepMessage)

    for (let run = 1; run <= 3; run++) {
      const before = await snapshot(phaseBot, `run-${run}-before`)
      let consumeError = null
      try {
        await eatAttempt(attackerBot)
      } catch (error) {
        consumeError = String(error.stack || error)
      }
      const after = await snapshot(phaseBot, `run-${run}-after`)
      const xpGain = Number(after.alchemy_xp) - Number(before.alchemy_xp)
      const cancelGain = Number(after.cancelled_consume_events) - Number(before.cancelled_consume_events)
      const trial = {
        run,
        before,
        after,
        xpGain,
        cancelGain,
        applePreserved: Number(before.enchanted_apples) === 1 && Number(after.enchanted_apples) === 1,
        consumeError,
        exploited: xpGain >= 500 && cancelGain === 1 && Number(after.enchanted_apples) === 1
      }
      report.trials.push(trial)
      record('trial', trial)
    }

    report.totalXpGain = report.trials.reduce((sum, trial) => sum + trial.xpGain, 0)
    report.totalCancelledConsumes = report.trials.reduce((sum, trial) => sum + trial.cancelGain, 0)
    report.confirmed = report.trials.length === 3 && report.trials.every(trial => trial.exploited)
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'reward-timing-xp-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'reward-timing-xp-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab reward timing XP complete') } catch (_) {}
    }
  }
  if (report.fatal || !report.confirmed) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'reward-timing-xp-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})
