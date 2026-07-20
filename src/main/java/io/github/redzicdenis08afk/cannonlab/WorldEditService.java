package io.github.redzicdenis08afk.cannonlab;

import com.sk89q.worldedit.EditSession;
import com.sk89q.worldedit.WorldEdit;
import com.sk89q.worldedit.WorldEditException;
import com.sk89q.worldedit.bukkit.BukkitAdapter;
import com.sk89q.worldedit.extent.clipboard.Clipboard;
import com.sk89q.worldedit.extent.clipboard.io.ClipboardFormat;
import com.sk89q.worldedit.extent.clipboard.io.ClipboardFormats;
import com.sk89q.worldedit.extent.clipboard.io.ClipboardReader;
import com.sk89q.worldedit.function.operation.Operation;
import com.sk89q.worldedit.function.operation.Operations;
import com.sk89q.worldedit.math.BlockVector3;
import com.sk89q.worldedit.regions.CuboidRegion;
import com.sk89q.worldedit.session.ClipboardHolder;
import com.sk89q.worldedit.world.block.BlockTypes;
import org.bukkit.Location;
import org.bukkit.World;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.util.Objects;

final class WorldEditService {

    void clear(World world, Location minimum, Location maximum) throws WorldEditException {
        BlockVector3 min = BlockVector3.at(
                Math.min(minimum.getBlockX(), maximum.getBlockX()),
                Math.min(minimum.getBlockY(), maximum.getBlockY()),
                Math.min(minimum.getBlockZ(), maximum.getBlockZ())
        );
        BlockVector3 max = BlockVector3.at(
                Math.max(minimum.getBlockX(), maximum.getBlockX()),
                Math.max(minimum.getBlockY(), maximum.getBlockY()),
                Math.max(minimum.getBlockZ(), maximum.getBlockZ())
        );

        try (EditSession editSession = WorldEdit.getInstance()
                .newEditSession(BukkitAdapter.adapt(world))) {
            editSession.setBlocks(new CuboidRegion(min, max),
                    Objects.requireNonNull(BlockTypes.AIR).getDefaultState());
        }
    }

    PasteResult paste(World world, File schematic, Location destination, boolean ignoreAir)
            throws IOException, WorldEditException {
        ClipboardFormat format = ClipboardFormats.findByFile(schematic);
        if (format == null) {
            throw new IOException("Unknown schematic format: " + schematic.getName());
        }

        Clipboard clipboard;
        try (ClipboardReader reader = format.getReader(new FileInputStream(schematic))) {
            clipboard = reader.read();
        }

        BlockVector3 target = BlockVector3.at(
                destination.getBlockX(), destination.getBlockY(), destination.getBlockZ());

        try (EditSession editSession = WorldEdit.getInstance()
                .newEditSession(BukkitAdapter.adapt(world))) {
            Operation operation = new ClipboardHolder(clipboard)
                    .createPaste(editSession)
                    .to(target)
                    .ignoreAirBlocks(ignoreAir)
                    .build();
            Operations.complete(operation);
        }

        BlockVector3 delta = target.subtract(clipboard.getOrigin());
        BlockVector3 minimum = clipboard.getRegion().getMinimumPoint().add(delta);
        BlockVector3 maximum = clipboard.getRegion().getMaximumPoint().add(delta);
        return new PasteResult(minimum, maximum, clipboard.getDimensions());
    }

    record PasteResult(BlockVector3 minimum, BlockVector3 maximum, BlockVector3 dimensions) {
    }
}
