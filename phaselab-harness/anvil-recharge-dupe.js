'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const VERSION = '1.21.11'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-anvil-recharge-dupe')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const report = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  stack: {
    client: VERSION,
    ExcellentEnchants: '5.4.3',
    chargesEnabled: true
  },
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
  bot.on('kicked', reason => record('kicked', { username, reason: String(reason) }))
  bot.on('error', error => record('bot_error', { username, error: String(error.stack || error) }))
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

async function waitForResult (bot, timeoutMs = 8000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const window = bot.currentWindow
    const item = window && window.slots ? window.slots[2] : null
    if (item && item.name && item.count > 0) return item
    await sleep(100)
  }
  throw new Error('Anvil result slot did not become available')
}

async function snapshot (phaseBot, label) {
  const message = await commandExpect(
    phaseBot,
    `/stacklab anvilsnapshot AttackerBot ${label}`,
    new RegExp(`STACKLAB ANVIL SNAPSHOT ${label} \\{`),
    8000
  )
  return parseJsonMessage(message)
}

const variants = [
  { name: 'normal_left', mouseButton: 0, mode: 0 },
  { name: 'shift_left', mouseButton: 0, mode: 1 },
  { name: 'hotbar_slot_0', mouseButton: 0, mode: 2 },
  { name: 'drop_stack', mouseButton: 1, mode: 4 },
  { name: 'double_click', mouseButton: 0, mode: 6 }
]

async function runTrial (phaseBot, attackerBot, variant) {
  if (attackerBot.currentWindow) attackerBot.closeWindow(attackerBot.currentWindow)
  await sleep(250)

  const windowOpen = onceWithTimeout(attackerBot, 'windowOpen', 10000)
  const prepMessagePromise = commandExpect(
    phaseBot,
    '/stacklab anvilprep AttackerBot',
    /STACKLAB ANVIL PREP \{/,
    12000
  )
  const [windowArgs, prepMessage] = await Promise.all([windowOpen, prepMessagePromise])
  const prep = parseJsonMessage(prepMessage)
  record('anvil_window_open', {
    variant: variant.name,
    windowType: attackerBot.currentWindow ? attackerBot.currentWindow.type : null,
    args: windowArgs.length
  })

  const resultItem = await waitForResult(attackerBot)
  const before = await snapshot(phaseBot, `${variant.name}-before`)
  let clickError = null
  try {
    await attackerBot.clickWindow(2, variant.mouseButton, variant.mode)
  } catch (error) {
    clickError = String(error.stack || error)
  }
  await sleep(1200)
  const after = await snapshot(phaseBot, `${variant.name}-after`)

  const validBaseline = Number(before.committed_token_total) === 1 &&
    Number(before.result_preview_token) === 1
  const duplicated = validBaseline && Number(after.committed_token_total) > 1
  const trial = {
    variant: variant.name,
    click: { mouseButton: variant.mouseButton, mode: variant.mode },
    prep: {
      token: prep.token,
      enchant_id: prep.enchant_id,
      chargeable: prep.chargeable,
      charges: prep.charges,
      max_charges: prep.max_charges
    },
    clientResult: { name: resultItem.name, count: resultItem.count },
    before,
    after,
    clickError,
    validBaseline,
    duplicated
  }
  record('trial_result', trial)
  return trial
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, attackerBot]

  try {
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival AttackerBot')

    for (const variant of variants) {
      report.trials.push(await runTrial(phaseBot, attackerBot, variant))
    }
    report.confirmed = report.trials.some(trial => trial.duplicated)
  } catch (error) {
    report.fatal = String(error.stack || error)
    record('fatal', { error: report.fatal })
  } finally {
    report.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'anvil-recharge-dupe-report.json'), JSON.stringify(report, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'anvil-recharge-dupe-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('PhaseLab anvil recharge dupe complete') } catch (_) {}
    }
  }

  if (report.fatal) process.exitCode = 1
}

main().catch(error => {
  report.fatal = String(error.stack || error)
  record('unhandled', { error: report.fatal })
  fs.writeFileSync(path.join(OUTPUT_DIR, 'anvil-recharge-dupe-report.json'), JSON.stringify(report, null, 2))
  process.exitCode = 1
})