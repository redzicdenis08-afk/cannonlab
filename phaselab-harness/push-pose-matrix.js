'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')

const Y = 65
const Z = 0.50
const STARTS = [0.25, 0.40, 0.55, 0.69]
const POSES = ['standing', 'sneaking']
const PULSES = [1, 2, 4, 8]
const MECHANISMS = ['piston_head', 'slime_piston', 'honey_piston', 'water_piston', 'boat_piston']
const TARGET_X = 2.35
const WITNESS = new Vec3(5, 65, 0)

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

async function command (bot, text, delay = 110) {
  bot.chat(text)
  await sleep(delay)
}

async function setupBase (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
}

async function clearArena (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 700)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 70)
  await command(bot, '/fill -5 63 -4 7 72 4 minecraft:air', 150)
  await command(bot, '/fill -5 64 -4 7 64 4 minecraft:stone', 100)
  await command(bot, '/fill 1 65 -1 1 68 1 minecraft:obsidian', 90)
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 70)
}

async function buildMechanism (bot, mechanism) {
  if (mechanism === 'piston_head' || mechanism === 'boat_piston') {
    await command(bot, '/setblock -1 65 0 minecraft:piston[facing=east]', 80)
    return { power: new Vec3(-2, 65, 0) }
  }
  if (mechanism === 'slime_piston') {
    await command(bot, '/setblock -2 65 0 minecraft:piston[facing=east]', 80)
    await command(bot, '/setblock -1 65 0 minecraft:slime_block', 80)
    return { power: new Vec3(-3, 65, 0) }
  }
  if (mechanism === 'honey_piston') {
    await command(bot, '/setblock -2 65 0 minecraft:piston[facing=east]', 80)
    await command(bot, '/setblock -1 65 0 minecraft:honey_block', 80)
    return { power: new Vec3(-3, 65, 0) }
  }
  if (mechanism === 'water_piston') {
    await command(bot, '/setblock -2 65 0 minecraft:piston[facing=east]', 80)
    await command(bot, '/setblock -1 65 0 minecraft:slime_block', 80)
    await command(bot, '/fill -1 65 -1 0 67 1 minecraft:water', 110)
    return { power: new Vec3(-3, 65, 0) }
  }
  throw new Error(`Unknown mechanism ${mechanism}`)
}

async function resetPlayer (bot, x) {
  const packetPromise = onceWithTimeout(bot._client, 'position', 2500)
  bot.chat(`/tp @s ${x} ${Y} ${Z} -90 0`)
  if (!await packetPromise) throw new Error('Reset position packet missing')
  await sleep(130)
  bot.entity.velocity = new Vec3(0, 0, 0)
}

async function setPose (bot, pose) {
  bot._client.write('player_input', {
    inputs: {
      shift: pose === 'sneaking'
    }
  })
  await sleep(120)
}

async function mountBoatFixture (bot, x) {
  bot.chat(`/summon minecraft:oak_boat ${x} ${Y} ${Z} {Rotation:[-90f,0f],Invulnerable:1b}`)
  await sleep(130)
  const mounted = onceWithTimeout(bot, 'mount', 1600)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  await sleep(100)
  return bot.vehicle || null
}

async function pulse (bot, power, count) {
  const started = process.hrtime.bigint()
  for (let index = 0; index < count; index++) {
    await command(bot, `/setblock ${power.x} ${power.y} ${power.z} minecraft:redstone_block`, 150)
    await command(bot, `/setblock ${power.x} ${power.y} ${power.z} minecraft:air`, 150)
  }
  return Number(process.hrtime.bigint() - started) / 1e6
}

async function authoritativeSnapshot (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 1500)
    bot.dismount()
    await dismounted
    await sleep(180)
  }
  const packetPromise = onceWithTimeout(bot._client, 'position', 2200)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  await sleep(100)
  return {
    packet: args ? args[0] : null,
    position: {
      x: bot.entity.position.x,
      y: bot.entity.position.y,
      z: bot.entity.position.z
    }
  }
}

async function openWitness (bot) {
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 70)
  let block = bot.blockAt(WITNESS)
  for (let attempt = 0; attempt < 12 && (!block || block.name !== 'barrel'); attempt++) {
    await sleep(80)
    block = bot.blockAt(WITNESS)
  }
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  }
  const opened = onceWithTimeout(bot, 'windowOpen', 1200)
  try {
    await bot.lookAt(WITNESS.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  if (!await opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function runTrial (bot, plan, id) {
  await clearArena(bot)
  const built = await buildMechanism(bot, plan.mechanism)
  await resetPlayer(bot, plan.startX)
  await setPose(bot, plan.pose)

  let mounted = false
  if (plan.mechanism === 'boat_piston') {
    const boat = await mountBoatFixture(bot, plan.startX)
    mounted = Boolean(boat)
    if (!mounted) {
      return {
        ...plan,
        id,
        mounted,
        pulseMs: 0,
        snapshot: { position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z } },
        beyond: false,
        witness: { opened: false, reason: 'mount_failed' },
        verified: false
      }
    }
  }

  const pulseMs = await pulse(bot, built.power, plan.pulses)
  await sleep(350)
  const snapshot = await authoritativeSnapshot(bot)
  const beyond = snapshot.position.x >= TARGET_X - 0.05
  const witness = beyond
    ? await openWitness(bot)
    : { opened: false, reason: 'not_beyond_wall' }
  await setPose(bot, 'standing')

  return {
    ...plan,
    id,
    mounted,
    pulseMs,
    snapshot,
    beyond,
    witness,
    verified: beyond && witness.opened
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'push-pose-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['id,mechanism,start_x,pose,pulses,mounted,pulse_ms,post_x,post_y,post_z,beyond,witness,verified']
  for (const result of results) {
    rows.push([
      result.id,
      result.mechanism,
      result.startX,
      result.pose,
      result.pulses,
      result.mounted,
      result.pulseMs.toFixed(3),
      result.snapshot.position.x.toFixed(6),
      result.snapshot.position.y.toFixed(6),
      result.snapshot.position.z.toFixed(6),
      result.beyond,
      result.witness.opened,
      result.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'push-pose-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab push pose matrix complete')
  } catch (_) {}
  await sleep(250)
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
  bot.on('kicked', reason => console.error('[PushPose kicked]', reason))
  bot.on('error', error => console.error('[PushPose error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('PushPose bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setupBase(bot)

    const plans = []
    for (const mechanism of MECHANISMS) {
      for (const startX of STARTS) {
        for (const pose of POSES) {
          for (const pulses of PULSES) {
            plans.push({ mechanism, startX, pose, pulses })
          }
        }
      }
    }

    const results = []
    for (let id = 0; id < plans.length; id++) {
      const result = await runTrial(bot, plans[id], id)
      results.push(result)
      writeReport(results, bot)
      console.log(`[PushPose] ${id + 1}/${plans.length}` +
        ` mechanism=${result.mechanism} start=${result.startX}` +
        ` pose=${result.pose} pulses=${result.pulses}` +
        ` postX=${result.snapshot.position.x.toFixed(3)}` +
        ` verified=${result.verified}`)
    }

    const verified = results.filter(result => result.verified).length
    console.log(`[PushPose] completed=${results.length} verified=${verified}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[PushPose fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
