package dev.denis.phaselab.guard;

import org.bukkit.NamespacedKey;
import org.bukkit.enchantments.Enchantment;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryType;
import org.bukkit.inventory.ItemStack;
import org.bukkit.plugin.java.JavaPlugin;

/**
 * Cancels ExcellentEnchants cursed grindstone transactions before AuraSkills
 * can award XP for a result that a later listener refuses to deliver.
 */
public final class GrindstoneXpGuardPlugin extends JavaPlugin implements Listener {
    @Override
    public void onEnable() {
        getServer().getPluginManager().registerEvents(this, this);
        getLogger().info("Grindstone XP transaction guard enabled");
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = false)
    public void onGrindstoneResult(InventoryClickEvent event) {
        if (event.getView().getTopInventory().getType() != InventoryType.GRINDSTONE) return;
        if (event.getRawSlot() != 2) return;

        ItemStack result = event.getView().getTopInventory().getItem(2);
        if (!containsExcellentEnchantsCurse(result)) return;

        event.setCancelled(true);
    }

    private boolean containsExcellentEnchantsCurse(ItemStack item) {
        if (item == null || item.getType().isAir()) return false;
        for (Enchantment enchantment : item.getEnchantments().keySet()) {
            NamespacedKey key = enchantment.getKey();
            if (key.getNamespace().equals("excellentenchants") && key.getKey().startsWith("curse_of_")) {
                return true;
            }
        }
        return false;
    }
}