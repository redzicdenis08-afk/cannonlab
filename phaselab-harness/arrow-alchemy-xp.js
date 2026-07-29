'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-arrow-alchemy-xp')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  trials: [],
  confirmed: false,
  fatal: null
}

function record (type, data = {}) {
  const row = { ts: new Date().toISOString(), type, ...data }
  transcript.push(row)
  console.log(JSON.stringify(row))
}

function onceWithTimeout (emitter, event, timeoutMs) {
  return new Promise((resolve, reject) => {
    let done = false
    const timer = setTimeout(() => finish(new Error(`Timeout waiting for ${event}`)), timeoutMs)
    const handler = (...args) => finish(null, args)
    function finish (error, value) {
      if (done) return
      done = true
      clearTimeout(timer)
      emitter.removeListener(event, handler)
      if (error) reject(error)
      else resolve(value)
    }
    emitter.once(event, handler)
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

async function command (bot, text, delay = 350) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 10000) {
  record('command', { username: bot.username, text, expect: String(pattern) })
  return await new Promise((resolve, reject) => {
    let done = false
    const timer = setTimeout(() => finish(new Error(`Timeout waiting for ${pattern}`)), timeoutMs)
    const handler = message => {
      const rendered = String(message)
      if (pattern.test(rendered)) finish(null, rendered)
    }
    function finish (error, value) {
      if (done) return
      done = true
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
  const start = message.indexOf('{')
  if (start < 0) throw new Error(`JSON missing: ${message}`)
  return JSON.parse(message.slice(start))
}

async function snapshot (phaseBot, label) {
  const message = await commandExpect(
    phaseBot,
    `/stacklab arrowxpsnapshot AttackerBot ${label}`,
    new RegExp(`STACKLAB ARROW XP SNAPSHOT ${label} \\{`),
    8000
  )
  return parseJson(message)
}

async function shoot (bot) {
  await bot.lookAt(new Vec3(14.5, 66.0, 30.5), true)
  bot.activateItem()
  await sleep(1250)
  bot.deactivateItem()
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
      '/stacklab arrowxpprep AttackerBot',
      /STACKLAB ARROW XP PREP \{/,
      12000
    )
    report.prep = parseJson(prepMessage)

    // The translated 1.21.11 client may not resolve the custom-enchanted bow's
    // registry name, but the authoritative prep snapshot already proves slot 0
    // contains BOWx1 and the fixture selected that hotbar slot server-side.
    await sleep(1200)
    if (!attackerBot.heldItem) throw new Error('AttackerBot held item did not synchronize')
    record('held_item', {
      name: attackerBot.heldItem.name || null,
      type: attackerBot.heldItem.type,
      count: attackerBot.heldItem.count
    })

    for (let index = 1; index <= 5; index++) {
      const before = await snapshot(phaseBot, `shot-${index}-before`)
      let shotError = null
      try {
        await shoot(attackerBot)
      } catch (error) {
        shotError = String(error.stack || error)
      }
      await sleep(2200)
      const after = await snapshot(phaseBot, `shot-${index}-after`)
      const xpGain = Number(after.alchemy_xp) - Number(before.alchemy_xp)
      const eventGain = Number(after.synthetic_lingering_events) - Number(before.synthetic_lingering_events)
      const arrowsUsed = Number(before.arrows) - Number(after.arrows)
      const exploited = eventGain > 0 && xpGain >= 60 && arrowsUsed >= 0 && arrowsUsed <= 1
      const trial = { index, before, after, xpGain, eventGain, arrowsUsed, shotError, exploited }
      report.trials.push(trial)
      record('trial_result', trial)
    }
    report.confirmed = report.trials.filter(trial => trial.exploited).length >= 2
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'arrow-alchemy-xp-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'arrow-alchemy-xp-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab arrow alchemy XP complete') } catch (_) {}
    }
  }
  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'arrow-alchemy-xp-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})