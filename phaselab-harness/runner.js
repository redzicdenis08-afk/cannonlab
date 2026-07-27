'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const ORIGIN = new Vec3(0.69, 65, 0.5)
const TARGET = new Vec3(2.74, 65, 0.5) // +2.05 blocks, fully beyond the one-block wall
const WITNESS = new Vec3(8, 65, 0)
const YAW_DEGREES = -90
const PITCH_DEGREES = 0

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

function positionPacket (pos, { onGround = true, horizontalCollision = false, look = false } = {}) {
  const fields = {
    x: pos.x,
    y: pos.y,
    z: pos.z,
    flags: {
      onGround,
      hasHorizontalCollision: horizontalCollision
    }
  }
  if (look) {
    fields.yaw = YAW_DEGREES
    fields.pitch = PITCH_DEGREES
  }
  return { packet: look ? 'position_look' : 'position', fields }
}

function lineSteps (stepSize, delayMs, options = {}) {
  const distance = TARGET.x - ORIGIN.x
  const steps = []
  for (let moved = stepSize; moved < distance - 1e-6; moved += stepSize) {
    steps.push({
      ...positionPacket(new Vec3(ORIGIN.x + moved, ORIGIN.y, ORIGIN.z), options),
      delayMs
    })
  }
  steps.push({ ...positionPacket(TARGET, options), delayMs })
  return steps
}

const tests = [
  {
    name: 'direct_position_grounded',
    steps: [{ ...positionPacket(TARGET, { onGround: true }), delayMs: 0 }]
  },
  {
    name: 'direct_position_look_grounded',
    steps: [{ ...positionPacket(TARGET, { onGround: true, look: true }), delayMs: 0 }]
  },
  {
    name: 'direct_position_airborne',
    steps: [{ ...positionPacket(TARGET, { onGround: false }), delayMs: 0 }]
  },
  {
    name: 'direct_horizontal_collision_flag',
    steps: [{ ...positionPacket(TARGET, { onGround: true, horizontalCollision: true }), delayMs: 0 }]
  },
  {
    name: 'two_stage_50ms',
    steps: [
      { ...positionPacket(new Vec3(1.70, 65, 0.5), { onGround: true }), delayMs: 50 },
      { ...positionPacket(TARGET, { onGround: true }), delayMs: 0 }
    ]
  },
  {
    name: 'segmented_0_50_50ms',
    steps: lineSteps(0.50, 50, { onGround: true })
  },
  {
    name: 'segmented_0_25_50ms',
    steps: lineSteps(0.25, 50, { onGround: true })
  },
  {
    name: 'segmented_0_25_100ms_airborne',
    steps: lineSteps(0.25, 100, { onGround: false })
  },
  {
    name: 'y_epsilon_up_then_target',
    steps: [
      { ...positionPacket(new Vec3(1.70, 65.0625, 0.5), { onGround: false }), delayMs: 50 },
      { ...positionPacket(new Vec3(TARGET.x, TARGET.y + 0.0625, TARGET.z), { onGround: false }), delayMs: 50 },
      { ...positionPacket(TARGET, { onGround: true }), delayMs: 0 }
    ]
  },
  {
    name: 'sneak_then_direct',
    before: bot => {
      bot._client.write('player_input', { inputs: { shift: true } })
    },
    after: bot => {
      bot._client.write('player_input', { inputs: { shift: false } })
    },
    steps: [{ ...positionPacket(TARGET, { onGround: true }), delayMs: 0 }]
  }
]

async function sendSteps (bot, test) {
  if (test.before) test.before(bot)
  for (const step of test.steps) {
    bot._client.write(step.packet, step.fields)
    if (step.delayMs > 0) await sleep(step.delayMs)
  }
  if (test.after) test.after(bot)
}

async function resetBot (bot) {
  const moved = onceWithTimeout(bot, 'forcedMove', 2500)
  bot.chat(`/tp ${USERNAME} ${ORIGIN.x} ${ORIGIN.y} ${ORIGIN.z} ${YAW_DEGREES} ${PITCH_DEGREES}`)
  const event = await moved
  if (!event) throw new Error('Server reset teleport did not arrive')
  bot.physicsEnabled = false
  bot.entity.position = ORIGIN.clone()
  bot.entity.velocity = new Vec3(0, 0, 0)
  await sleep(250)
}

async function verifyWitness (bot) {
  const block = bot.blockAt(WITNESS)
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `witness_missing:${block ? block.name : 'unloaded'}` }
  }

  bot.entity.position = TARGET.clone()
  const windowPromise = onceWithTimeout(bot, 'windowOpen', 1200)
  try {
    await bot.lookAt(WITNESS.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate_error:${error.message}` }
  }

  const opened = await windowPromise
  if (!opened) return { opened: false, reason: 'no_window_open' }

  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function runOne (bot, test) {
  await resetBot(bot)

  const corrections = []
  const startedNs = process.hrtime.bigint()
  const correctionHandler = () => {
    const elapsedMs = Number(process.hrtime.bigint() - startedNs) / 1e6
    corrections.push({
      elapsedMs,
      x: bot.entity.position.x,
      y: bot.entity.position.y,
      z: bot.entity.position.z
    })
  }
  bot.on('forcedMove', correctionHandler)

  await sendSteps(bot, test)
  bot.entity.position = TARGET.clone()
  await sleep(900)

  let witness = { opened: false, reason: 'not_attempted_after_correction' }
  if (corrections.length === 0) {
    witness = await verifyWitness(bot)
    await sleep(300)
  }

  bot.removeListener('forcedMove', correctionHandler)

  let verdict
  if (corrections.length > 0) verdict = 'SERVER_SETBACK'
  else if (witness.opened) verdict = 'SERVER_VERIFIED_WITNESS_OPEN'
  else verdict = 'SILENT_IGNORE_OR_UNVERIFIED'

  return {
    name: test.name,
    origin: { x: ORIGIN.x, y: ORIGIN.y, z: ORIGIN.z },
    target: { x: TARGET.x, y: TARGET.y, z: TARGET.z },
    packetCount: test.steps.length,
    corrections,
    witness,
    verdict
  }
}

function writeReports (results, metadata) {
  const report = { metadata, results }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'report.json'), JSON.stringify(report, null, 2))

  const rows = ['test,packet_count,verdict,first_correction_ms,correction_x,correction_y,correction_z,witness_reason']
  for (const result of results) {
    const first = result.corrections[0]
    rows.push([
      result.name,
      result.packetCount,
      result.verdict,
      first ? first.elapsedMs.toFixed(3) : '',
      first ? first.x.toFixed(6) : '',
      first ? first.y.toFixed(6) : '',
      first ? first.z.toFixed(6) : '',
      result.witness.reason
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'report.csv'), `${rows.join('\n')}\n`)
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

  bot.on('kicked', reason => console.error('[kicked]', reason))
  bot.on('error', error => console.error('[bot error]', error))

  const spawned = await onceWithTimeout(bot, 'spawn', 30000)
  if (!spawned) throw new Error('Bot did not spawn within 30 seconds')

  bot.physicsEnabled = false
  await sleep(1500)

  const results = []
  for (const test of tests) {
    console.log(`[PhaseLab] running ${test.name}`)
    const result = await runOne(bot, test)
    results.push(result)
    const first = result.corrections[0]
    console.log(
      `[PhaseLab] ${test.name}: ${result.verdict}` +
      (first ? ` after ${first.elapsedMs.toFixed(1)} ms` : '') +
      ` (${result.witness.reason})`
    )
  }

  const metadata = {
    generatedAt: new Date().toISOString(),
    host: HOST,
    port: PORT,
    clientVersion: bot.version,
    serverBrand: bot.game.serverBrand,
    username: USERNAME,
    origin: ORIGIN,
    target: TARGET,
    witness: WITNESS
  }
  writeReports(results, metadata)

  const verified = results.filter(result => result.verdict === 'SERVER_VERIFIED_WITNESS_OPEN')
  console.log(`[PhaseLab] completed ${results.length} tests; server-verified=${verified.length}`)
  bot.quit('PhaseLab complete')
}

main().catch(error => {
  console.error('[PhaseLab fatal]', error)
  process.exitCode = 1
})
