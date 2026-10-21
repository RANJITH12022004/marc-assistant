package com.marc.island;

import android.os.Bundle;
import android.os.Handler;
import android.view.accessibility.AccessibilityNodeInfo;

import java.util.ArrayList;
import java.util.List;

/** Finds, types, and taps inside the foreground app. One retry, then a spoken failure. */
final class ScreenHands {
    private ScreenHands() {}

    interface Step {
        boolean go();

        String fail();
    }

    static void play(Handler handler, Step[] steps) {
        handler.postDelayed(() -> playAt(handler, steps, 0), 900);
    }

    private static void playAt(Handler handler, Step[] steps, int index) {
        if (index >= steps.length) {
            return;
        }
        Step step = steps[index];
        if (step.go()) {
            handler.postDelayed(() -> playAt(handler, steps, index + 1), 700);
            return;
        }
        handler.postDelayed(() -> {
            if (step.go()) {
                handler.postDelayed(() -> playAt(handler, steps, index + 1), 700);
            } else {
                PhoneActions.fail(step.fail());
            }
        }, 600);
    }

    static boolean hasEditable() {
        AccessibilityNodeInfo root = IslandAccess.root();
        if (root == null) {
            return false;
        }
        List<AccessibilityNodeInfo> edits = new ArrayList<>();
        collect(root, edits, new String[0], true);
        boolean found = !edits.isEmpty();
        root.recycle();
        return found;
    }

    static boolean clickSong(String query) {
        if (query == null || query.trim().isEmpty()) {
            return false;
        }
        AccessibilityNodeInfo root = IslandAccess.root();
        if (root == null) {
            return false;
        }
        List<AccessibilityNodeInfo> hits = new ArrayList<>();
        collectSong(root, hits, query.toLowerCase());
        boolean clicked = false;
        for (AccessibilityNodeInfo node : hits) {
            if (click(node)) {
                clicked = true;
                break;
            }
        }
        root.recycle();
        return clicked;
    }

    static boolean clickAny(String... labels) {
        AccessibilityNodeInfo root = IslandAccess.root();
        if (root == null) {
            return false;
        }
        List<AccessibilityNodeInfo> hits = new ArrayList<>();
        collect(root, hits, labels, false);
        for (AccessibilityNodeInfo node : hits) {
            if (click(node)) {
                root.recycle();
                return true;
            }
        }
        root.recycle();
        return false;
    }

    static boolean typeInto(String text, boolean lastEditable) {
        AccessibilityNodeInfo root = IslandAccess.root();
        if (root == null) {
            return false;
        }
        List<AccessibilityNodeInfo> edits = new ArrayList<>();
        collect(root, edits, new String[0], true);
        if (edits.isEmpty()) {
            root.recycle();
            return false;
        }
        AccessibilityNodeInfo field = lastEditable ? edits.get(edits.size() - 1) : edits.get(0);
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text == null ? "" : text);
        boolean ok = field.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                && field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
        if (!ok) {
            ok = field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
        }
        root.recycle();
        return ok;
    }

    private static boolean click(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo current = node;
        while (current != null) {
            if (current.isClickable() && current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                return true;
            }
            current = current.getParent();
        }
        return false;
    }

    private static void collect(AccessibilityNodeInfo node, List<AccessibilityNodeInfo> out, String[] labels, boolean editsOnly) {
        if (node == null) {
            return;
        }
        if (editsOnly) {
            if (node.isEditable()) {
                out.add(node);
            }
        } else if (matches(node, labels)) {
            out.add(node);
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            collect(node.getChild(i), out, labels, editsOnly);
        }
    }

    private static void collectSong(AccessibilityNodeInfo node, List<AccessibilityNodeInfo> out, String query) {
        if (node == null) {
            return;
        }
        if (!node.isEditable()) {
            String text = node.getText() == null ? "" : node.getText().toString().toLowerCase();
            String desc = node.getContentDescription() == null ? "" : node.getContentDescription().toString().toLowerCase();
            String blob = text + " " + desc;
            if (blob.contains(query) && blob.length() < 120) {
                out.add(node);
            }
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            collectSong(node.getChild(i), out, query);
        }
    }

    private static boolean matches(AccessibilityNodeInfo node, String[] labels) {
        String text = node.getText() == null ? "" : node.getText().toString();
        String desc = node.getContentDescription() == null ? "" : node.getContentDescription().toString();
        String blob = (text + " " + desc).toLowerCase();
        for (String label : labels) {
            if (label != null && !label.isEmpty() && blob.contains(label.toLowerCase())) {
                return true;
            }
        }
        return false;
    }
}
