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
import com.sk89q.worldedit.util.SideEffectSet;
import com.sk89q.worldedit.world.block.BlockTypes;
import org.bukkit.Location;
import org.bukkit.World;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

final class WorldEditService {
    private final Map<Path, CachedClipboardMetadata> metadataCache = new HashMap<>();

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
        return paste(world, schematic, destination, ignoreAir, false);
    }

    PasteResult paste(
            World world,
            File schematic,
            Location destination,
            boolean ignoreAir,
            boolean suppressSideEffects
    ) throws IOException, WorldEditException {
        Clipboard clipboard = readClipboard(schematic);
        cacheMetadata(schematic, clipboard);

        BlockVector3 target = BlockVector3.at(
                destination.getBlockX(), destination.getBlockY(), destination.getBlockZ());

        try (EditSession editSession = WorldEdit.getInstance()
                .newEditSession(BukkitAdapter.adapt(world))) {
            if (suppressSideEffects) {
                editSession.setFastMode(true);
                editSession.setSideEffectApplier(SideEffectSet.none());
            }
            Operation operation = new ClipboardHolder(clipboard)
                    .createPaste(editSession)
                    .to(target)
                    .ignoreAirBlocks(ignoreAir)
                    .build();
            Operations.complete(operation);
        }

        return pasteResult(clipboard, target);
    }

    PasteResult inspectPaste(File schematic, Location destination) throws IOException {
        ClipboardMetadata metadata = clipboardMetadata(schematic);
        BlockVector3 target = BlockVector3.at(
                destination.getBlockX(), destination.getBlockY(), destination.getBlockZ());
        return pasteResult(metadata, target);
    }

    private Clipboard readClipboard(File schematic) throws IOException {
        ClipboardFormat format = ClipboardFormats.findByFile(schematic);
        if (format == null) {
            throw new IOException("Unknown schematic format: " + schematic.getName());
        }
        try (ClipboardReader reader = format.getReader(new FileInputStream(schematic))) {
            return reader.read();
        }
    }

    private PasteResult pasteResult(Clipboard clipboard, BlockVector3 target) {
        return pasteResult(metadata(clipboard), target);
    }

    private PasteResult pasteResult(ClipboardMetadata metadata, BlockVector3 target) {
        BlockVector3 delta = target.subtract(metadata.origin());
        BlockVector3 minimum = metadata.minimum().add(delta);
        BlockVector3 maximum = metadata.maximum().add(delta);
        return new PasteResult(minimum, maximum, metadata.dimensions());
    }

    private ClipboardMetadata clipboardMetadata(File schematic) throws IOException {
        Path path = schematic.toPath().toAbsolutePath().normalize();
        long size = Files.size(path);
        long modified = Files.getLastModifiedTime(path).toMillis();
        CachedClipboardMetadata cached = metadataCache.get(path);
        if (cached != null && cached.size() == size && cached.modified() == modified) {
            return cached.metadata();
        }
        Clipboard clipboard = readClipboard(schematic);
        ClipboardMetadata metadata = metadata(clipboard);
        metadataCache.put(path, new CachedClipboardMetadata(size, modified, metadata));
        return metadata;
    }

    private void cacheMetadata(File schematic, Clipboard clipboard) throws IOException {
        Path path = schematic.toPath().toAbsolutePath().normalize();
        metadataCache.put(
                path,
                new CachedClipboardMetadata(
                        Files.size(path),
                        Files.getLastModifiedTime(path).toMillis(),
                        metadata(clipboard)
                )
        );
    }

    private ClipboardMetadata metadata(Clipboard clipboard) {
        return new ClipboardMetadata(
                clipboard.getOrigin(),
                clipboard.getRegion().getMinimumPoint(),
                clipboard.getRegion().getMaximumPoint(),
                clipboard.getDimensions()
        );
    }

    record PasteResult(BlockVector3 minimum, BlockVector3 maximum, BlockVector3 dimensions) {
    }

    private record ClipboardMetadata(
            BlockVector3 origin,
            BlockVector3 minimum,
            BlockVector3 maximum,
            BlockVector3 dimensions
    ) {
    }

    private record CachedClipboardMetadata(
            long size,
            long modified,
            ClipboardMetadata metadata
    ) {
    }
}
