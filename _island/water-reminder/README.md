# Water reminder animation handoff

An original red-and-blue spider-themed hero concept for the Marc Android Dynamic Island project.

## Files

- `character-sheet.svg` — six consistent character poses for design reference.
- `motion-sheet.svg` — eight numbered beats describing the reminder interaction.
- `preview.html` — self-contained animated browser prototype; open it directly.

## Preview behavior

The demo loops through the reveal, reminder, and water-offer sequence. Choose **I drank water** to trigger the sip, web shot, and swing-away. Choose **Remind me later** to dismiss. The cycle is intentionally short for preview; use it as a visual reference when connecting the app to an hourly reminder.

## Existing app context

The Android capsule overlay lives in `_island/IslandService.java`; its pill layout and content are built there. `_island/IslandBackdropView.java` draws the capsule's animated rim. The app uses a foreground service and Android accessibility overlay, so a future implementation can host a custom animated view in the pill and schedule reminders from the service. These files are an art and behavior handoff and do not change the app.
