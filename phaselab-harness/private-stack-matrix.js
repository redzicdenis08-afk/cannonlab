'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25566)
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output-private-stack')
const VERSION = '1.21.11'
const ONLY_CRAFTER = process.env.PHASELAB_ONLY_CRAFTER === '1'
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const transcript = []
const results = {
  startedAt: new Date().toISOString(),
  host: HOST,
  port: PORT,
  version: VERSION,
  phases: []
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
  record('spawn', { username, position: bot.entity.position })
  return bot
}

async function command (bot, text, delay = 450) {
  record('command', { username: bot.username, text })
  bot.chat(text)
  await sleep(delay)
}

async function commandExpect (bot, text, pattern, timeoutMs = 5000) {
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

async function waitForInventoryItem (bot, itemName, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const item = bot.inventory.items().find(entry => entry.name === itemName)
    if (item) return item
    await sleep(100)
  }
  return null
}

async function equipAndActivate (bot, itemName, blockPos, faceVector) {
  const item = await waitForInventoryItem(bot, itemName)
  if (!item) throw new Error(`${bot.username} missing ${itemName}`)
  await bot.equip(item, 'hand')
  await sleep(150)
  const block = bot.blockAt(blockPos)
  if (!block) throw new Error(`Missing target block at ${blockPos}`)
  await bot.lookAt(block.position.offset(0.5, 0.5, 0.5), true)
  await bot.activateBlock(block, faceVector)
  await sleep(1500)
  return {
    target: block.name,
    heldAfter: bot.heldItem ? { name: bot.heldItem.name, count: bot.heldItem.count } : null
  }
}

async function equipAndDig (bot, itemName, blockPos) {
  const item = await waitForInventoryItem(bot, itemName)
  if (!item) throw new Error(`${bot.username} missing ${itemName}`)
  await bot.equip(item, 'hand')
  const block = bot.blockAt(blockPos)
  if (!block) throw new Error(`Missing dig block at ${blockPos}`)
  await bot.lookAt(block.position.offset(0.5, 0.5, 0.5), true)
  await bot.dig(block, true)
  await sleep(1200)
  return { target: block.name }
}

async function openGrindstoneAndLoadSword (phaseBot, bot, blockPos) {
  const block = bot.blockAt(blockPos)
  if (!block) throw new Error(`Missing grindstone at ${blockPos}`)
  await bot.lookAt(block.position.offset(0.5, 0.5, 0.5), true)
  const window = await bot.openBlock(block)
  await sleep(450)

  await commandExpect(
    phaseBot,
    `/stacklab grindstoneprep ${bot.username}`,
    /STACKLAB GRINDSTONE PREP .*accepted=true/,
    5000
  )
  await sleep(900)
  record('grindstone_loaded', {
    windowType: window.type,
    input0: window.slots[0]?.name || null,
    input1: window.slots[1]?.name || null,
    result: window.slots[2]?.name || null
  })
  if (!window.slots[2]) {
    try { bot.closeWindow(window) } catch {}
    throw new Error('Grindstone result slot did not populate')
  }
  return window
}

async function clickGrindstoneResult (bot, window, run) {
  let clickError = null
  try {
    await bot.clickWindow(2, 0, 0)
  } catch (error) {
    clickError = String(error.stack || error)
  }
  await sleep(650)
  const state = {
    run,
    clickError,
    input0: window.slots[0]?.name || null,
    result: window.slots[2]?.name || null
  }
  record('grindstone_click_client', state)
  return state
}

async function openBrewingStand (bot, blockPos) {
  const block = bot.blockAt(blockPos)
  if (!block) throw new Error(`Missing brewing stand at ${blockPos}`)
  await bot.lookAt(block.position.offset(0.5, 0.5, 0.5), true)
  const window = await bot.openBlock(block)
  await sleep(450)
  if (!String(window.type).includes('brewing')) throw new Error(`Unexpected brewing window ${window.type}`)
  return window
}

async function equipAndServerBreak (phaseBot, playerBot, itemName, blockPos) {
  const item = await waitForInventoryItem(playerBot, itemName)
  if (!item) throw new Error(`${playerBot.username} missing ${itemName}`)
  await playerBot.equip(item, 'hand')
  await sleep(200)
  const response = await commandExpect(
    phaseBot,
    `/stacklab break ${playerBot.username} ${blockPos.x} ${blockPos.y} ${blockPos.z}`,
    /STACKLAB BREAK .*accepted=true/,
    5000
  )
  await sleep(1300)
  return { response }
}

async function readyAuraAbility (bot, itemName) {
  const item = await waitForInventoryItem(bot, itemName)
  if (!item) throw new Error(`${bot.username} missing ${itemName}`)
  await bot.equip(item, 'hand')
  await sleep(150)
  bot.activateItem()
  await sleep(650)
  bot.deactivateItem()
  return { held: bot.heldItem ? bot.heldItem.name : null }
}

async function phase (name, fn) {
  const started = Date.now()
  try {
    const detail = await fn()
    const entry = { name, ok: true, elapsedMs: Date.now() - started, detail }
    results.phases.push(entry)
    record('phase_result', entry)
  } catch (error) {
    const entry = { name, ok: false, elapsedMs: Date.now() - started, error: String(error.stack || error) }
    results.phases.push(entry)
    record('phase_result', entry)
  }
}

async function main () {
  const phaseBot = await connect('PhaseBot')
  const victimBot = await connect('VictimBot')
  const attackerBot = await connect('AttackerBot')
  const bots = [phaseBot, victimBot, attackerBot]

  try {
    await command(phaseBot, '/gamerule doDaylightCycle false')
    await command(phaseBot, '/time set day')
    await command(phaseBot, '/difficulty peaceful')
    await command(phaseBot, '/gamemode creative PhaseBot')
    await command(phaseBot, '/gamemode survival VictimBot')
    await command(phaseBot, '/gamemode survival AttackerBot')
    await command(phaseBot, '/effect give VictimBot minecraft:resistance infinite 255 true')
    await command(phaseBot, '/effect give AttackerBot minecraft:resistance infinite 255 true')

    await phase('factions_setup', async () => {
      await command(phaseBot, '/stacklab build', 700)
      await command(phaseBot, '/stacklab portalbuild', 700)
      await command(phaseBot, '/tp VictimBot 17.5 65 0.5')
      await command(victimBot, '/f create Victims', 900)
      await command(phaseBot, '/fa power set VictimBot 100', 600)
      await command(victimBot, '/f claim', 900)
      await command(phaseBot, '/tp VictimBot 17.5 65 21.5')
      await command(victimBot, '/f claim', 900)
      await command(phaseBot, '/tp AttackerBot 14.5 65 0.5')
      await command(attackerBot, '/f create Attackers', 900)
      await command(phaseBot, '/fa power set AttackerBot 100', 600)
      await command(attackerBot, '/f claim', 900)
      await command(phaseBot, '/tp AttackerBot 14.5 65 21.5')
      await command(attackerBot, '/f claim', 900)
      const witness = await commandExpect(
        phaseBot,
        '/stacklab claimsnapshot setup',
        /STACKLAB CLAIM WITNESS .*"attacker_tag":"Attackers".*"victim_tag":"Victims".*"attacker_portal_tag":"Attackers".*"victim_portal_tag":"Victims".*"verified":true/,
        6000
      )
      await command(victimBot, '/f show', 400)
      await command(attackerBot, '/f show', 400)
      return { victim: victimBot.entity.position, attacker: attackerBot.entity.position, witness }
    })

    await phase('factions_enemy_crafter_theft', async () => {
      await command(phaseBot, '/stacklab build', 650)
      await command(phaseBot, '/clear AttackerBot', 300)
      await command(phaseBot, '/stacklab snapshot crafter-before', 300)
      await command(phaseBot, '/tp AttackerBot 15.25 65 6.5 -90 0', 500)

      const block = attackerBot.blockAt(new Vec3(16, 65, 6))
      if (!block) throw new Error('Victim crafter missing')
      await attackerBot.lookAt(block.position.offset(0.5, 0.5, 0.5), true)

      let window = null
      let openError = null
      let visibleNetherite = 0
      let clickError = null
      try {
        window = await attackerBot.openBlock(block)
        await sleep(700)
        visibleNetherite = window.slots
          .slice(0, window.inventoryStart)
          .filter(item => item?.name === 'netherite_block')
          .reduce((sum, item) => sum + item.count, 0)
        if (visibleNetherite > 0) {
          const slot = window.slots
            .slice(0, window.inventoryStart)
            .findIndex(item => item?.name === 'netherite_block')
          await attackerBot.clickWindow(slot, 0, 1)
          await sleep(900)
        }
      } catch (error) {
        if (window) clickError = String(error.stack || error)
        else openError = String(error.stack || error)
      } finally {
        if (window) {
          try { attackerBot.closeWindow(window) } catch {}
        }
      }

      await command(phaseBot, '/stacklab snapshot crafter-after', 300)
      return { block: block.name, visibleNetherite, openError, clickError }
    })

    if (ONLY_CRAFTER) return

    await phase('auraskills_excellentenchants_infinite_grindstone_xp', async () => {
      await command(phaseBot, '/stacklab build', 650)
      await command(phaseBot, '/clear AttackerBot')
      await command(phaseBot, '/stacklab give AttackerBot diamond_sword excellentenchants:curse_of_fragility 1', 650)
      // A curse-only item has no removable enchant and vanilla leaves the
      // result empty. Sharpness supplies the removable layer while the custom
      // curse remains on the result and triggers ExcellentEnchants' cancel.
      await command(phaseBot, '/enchant AttackerBot minecraft:sharpness 5', 650)
      await command(phaseBot, '/tp AttackerBot 12.5 65 5.5 -90 0', 500)
      const window = await openGrindstoneAndLoadSword(phaseBot, attackerBot, new Vec3(13, 65, 5))
      const clicks = []
      for (let run = 1; run <= 3; run++) {
        await command(phaseBot, `/stacklab snapshot grindstone-before-${run}`, 300)
        clicks.push(await clickGrindstoneResult(attackerBot, window, run))
        await command(phaseBot, `/stacklab snapshot grindstone-after-${run}`, 300)
      }
      try { window.close() } catch {}
      return { clicks }
    })

    if (attackerBot.currentWindow) {
      try { attackerBot.closeWindow(attackerBot.currentWindow) } catch {}
      await sleep(250)
    }

    await phase('auraskills_five_cycle_alchemy_xp_amplifier', async () => {
      await command(phaseBot, '/stacklab build', 650)
      await command(phaseBot, '/tp AttackerBot 12.5 67 9.5 -90 0', 500)

      // Opening once assigns AuraSkills' brewing-stand owner metadata.
      let window = await openBrewingStand(attackerBot, new Vec3(13, 67, 9))
      try { attackerBot.closeWindow(window) } catch {}
      await sleep(300)

      for (let run = 1; run <= 5; run++) {
        await command(phaseBot, `/stacklab alchemycycle ${run}`, 250)
        await sleep(2300)
        await command(phaseBot, `/stacklab snapshot alchemy-cycle-${run}`, 300)
      }

      await command(phaseBot, '/stacklab alchemyfinal', 500)
      window = await openBrewingStand(attackerBot, new Vec3(13, 67, 9))
      await command(phaseBot, '/stacklab snapshot alchemy-before-take', 300)
      let clickError = null
      try {
        await attackerBot.clickWindow(0, 0, 0)
      } catch (error) {
        clickError = String(error.stack || error)
      }
      await sleep(700)
      await command(phaseBot, '/stacklab snapshot alchemy-after-take', 300)
      try { attackerBot.closeWindow(window) } catch {}
      return { clickError }
    })

    if (attackerBot.currentWindow) {
      try { attackerBot.closeWindow(attackerBot.currentWindow) } catch {}
      await sleep(250)
    }

    for (let run = 1; run <= 3; run++) {
      await phase(`portal_factions_run_${run}`, async () => {
        await command(phaseBot, '/kill @e[type=minecraft:item]', 250)
        await command(phaseBot, '/stacklab cancelportal false')
        await command(phaseBot, '/stacklab portalbuild', 700)
        await command(phaseBot, '/clear AttackerBot')
        await command(phaseBot, '/give AttackerBot minecraft:ender_eye 1')
        await command(phaseBot, '/tp AttackerBot 14.25 65 21.5 -90 0', 500)
        const interaction = await equipAndActivate(attackerBot, 'ender_eye', new Vec3(15, 65, 21), new Vec3(-1, 0, 0))
        await command(phaseBot, `/stacklab portalsnapshot factions-${run}`, 400)
        return interaction
      })
    }

    for (let run = 1; run <= 2; run++) {
      await phase(`portal_cancel_control_${run}`, async () => {
        await command(phaseBot, '/kill @e[type=minecraft:item]', 250)
        await command(phaseBot, '/stacklab cancelportal true')
        await command(phaseBot, '/stacklab portalbuild', 700)
        await command(phaseBot, '/clear AttackerBot')
        await command(phaseBot, '/give AttackerBot minecraft:ender_eye 1')
        await command(phaseBot, '/tp AttackerBot 14.25 65 21.5 -90 0', 500)
        const interaction = await equipAndActivate(attackerBot, 'ender_eye', new Vec3(15, 65, 21), new Vec3(-1, 0, 0))
        await command(phaseBot, `/stacklab portalsnapshot control-${run}`, 400)
        return interaction
      })
    }
    await command(phaseBot, '/stacklab cancelportal false')

    for (let run = 1; run <= 3; run++) {
      await phase(`auraskills_terraform_claim_boundary_${run}`, async () => {
        await command(phaseBot, '/stacklab build', 650)
        await command(phaseBot, `/stacklab snapshot aura-terraform-before-${run}`)
        await command(phaseBot, '/clear AttackerBot')
        await command(phaseBot, '/give AttackerBot minecraft:diamond_shovel 1')
        await command(phaseBot, '/skills skill setlevel AttackerBot excavation 100', 750)
        await command(phaseBot, '/skills manaability resetcooldown AttackerBot terraform true', 750)
        await command(phaseBot, '/tp AttackerBot 14.25 65 2.5 -90 0', 500)
        const ready = await readyAuraAbility(attackerBot, 'diamond_shovel')
        const dig = await equipAndServerBreak(phaseBot, attackerBot, 'diamond_shovel', new Vec3(15, 65, 2))
        await sleep(1800)
        await command(phaseBot, `/stacklab snapshot aura-terraform-after-${run}`)
        return { ready, dig }
      })
    }

    for (let run = 1; run <= 3; run++) {
      await phase(`auraskills_treecapitator_claim_boundary_${run}`, async () => {
        await command(phaseBot, '/stacklab build', 650)
        await command(phaseBot, `/stacklab snapshot aura-tree-before-${run}`)
        await command(phaseBot, '/clear AttackerBot')
        await command(phaseBot, '/give AttackerBot minecraft:diamond_axe 1')
        await command(phaseBot, '/skills skill setlevel AttackerBot foraging 100', 750)
        await command(phaseBot, '/skills manaability resetcooldown AttackerBot treecapitator true', 750)
        await command(phaseBot, '/tp AttackerBot 14.25 65 0.5 -90 0', 500)
        const ready = await readyAuraAbility(attackerBot, 'diamond_axe')
        const dig = await equipAndServerBreak(phaseBot, attackerBot, 'diamond_axe', new Vec3(15, 65, 0))
        await sleep(1800)
        await command(phaseBot, `/stacklab snapshot aura-tree-after-${run}`)
        return { ready, dig }
      })
    }

    await phase('treefeller_claim_boundary', async () => {
      await command(phaseBot, '/stacklab build', 650)
      await command(phaseBot, '/stacklab snapshot tree-before')
      await command(phaseBot, '/stacklab give AttackerBot diamond_axe excellentenchants:treefeller 1', 500)
      await command(phaseBot, '/tp AttackerBot 14.25 65 0.5 -90 0', 500)
      const dig = await equipAndServerBreak(phaseBot, attackerBot, 'diamond_axe', new Vec3(15, 65, 0))
      await command(phaseBot, '/stacklab snapshot tree-after')
      return dig
    })

    await phase('tunnel_claim_boundary', async () => {
      await command(phaseBot, '/stacklab build', 650)
      await command(phaseBot, '/stacklab snapshot tunnel-before')
      await command(phaseBot, '/stacklab give AttackerBot diamond_pickaxe excellentenchants:tunnel 3', 500)
      await command(phaseBot, '/tp AttackerBot 14.25 66 4.5 -90 0', 500)
      const dig = await equipAndServerBreak(phaseBot, attackerBot, 'diamond_pickaxe', new Vec3(15, 66, 4))
      await command(phaseBot, '/stacklab snapshot tunnel-after')
      return dig
    })

    await phase('blast_mining_claim_boundary', async () => {
      await command(phaseBot, '/stacklab build', 650)
      await command(phaseBot, '/stacklab snapshot blast-before')
      await command(phaseBot, '/stacklab give AttackerBot diamond_pickaxe excellentenchants:blast_mining 10', 500)
      await command(phaseBot, '/tp AttackerBot 14.25 66 4.5 -90 0', 500)
      const dig = await equipAndServerBreak(phaseBot, attackerBot, 'diamond_pickaxe', new Vec3(15, 66, 4))
      await command(phaseBot, '/stacklab snapshot blast-after')
      return dig
    })

    await phase('piston_claim_boundary', async () => {
      await command(phaseBot, '/stacklab build', 650)
      await command(phaseBot, '/stacklab snapshot piston-before')
      await command(phaseBot, '/tp AttackerBot 13.5 65 11.5 0 0', 400)
      const lever = attackerBot.blockAt(new Vec3(14, 65, 11))
      if (!lever) throw new Error('Lever missing')
      await attackerBot.lookAt(lever.position.offset(0.5, 0.5, 0.5), true)
      await attackerBot.activateBlock(lever)
      await sleep(900)
      await command(phaseBot, '/stacklab snapshot piston-after')
      return { lever: lever.name }
    })

    await phase('hopper_cross_boundary', async () => {
      await command(phaseBot, '/stacklab build', 650)
      await command(phaseBot, '/stacklab snapshot hopper-before')
      await sleep(4500)
      await command(phaseBot, '/stacklab snapshot hopper-after')
      return { waitedMs: 4500 }
    })
  } finally {
    results.finishedAt = new Date().toISOString()
    fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-results.json'), JSON.stringify(results, null, 2))
    fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
    for (const bot of bots) {
      try { bot.quit('matrix complete') } catch {}
    }
  }
}

main().catch(error => {
  record('fatal', { error: String(error.stack || error) })
  results.fatal = String(error.stack || error)
  results.finishedAt = new Date().toISOString()
  fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-results.json'), JSON.stringify(results, null, 2))
  fs.writeFileSync(path.join(OUTPUT_DIR, 'private-stack-transcript.jsonl'), transcript.map(row => JSON.stringify(row)).join('\n') + '\n')
  process.exitCode = 1
})
