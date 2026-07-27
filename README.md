# Free Fantasy Draft Board

A no-subscription fantasy football rankings and draft board.

## What works immediately

- Drag full rows to reorder rankings instantly.
- One shared player state across Available, Drafted, All, and every position tab.
- Check Drafted anywhere and every tab updates immediately.
- Search and position filters.
- Internet-rank columns, 2026 projections, 2024/2025 metrics, injury/news fields.
- Player detail drawer with category sliders and notes.
- JSON backup/restore and CSV import.
- All personal rankings and draft status are stored in your browser, not sent anywhere.

## Open it now

Double-click `index.html`. No install and no server are required.

Use the same browser and device during your draft. Export a JSON backup before the draft.

## Host it online for free with GitHub Pages

1. Create a free GitHub account and a **public** repository.
2. Upload every file and folder in this package.
3. In the repository, open **Settings → Pages**.
4. Under **Build and deployment**, choose **Deploy from a branch**.
5. Choose the `main` branch and `/ (root)`, then save.
6. GitHub will show the free site address after deployment.

A public repository is required for GitHub Pages on GitHub Free. Your drafted players and personal rankings remain in browser localStorage and are not committed to the public repository.

## Turn on free daily updates

The included `.github/workflows/daily-update.yml` runs each morning and updates `data/players.js`.

1. Open the repository's **Actions** tab.
2. Enable workflows if GitHub asks.
3. Open **Daily fantasy data update** and click **Run workflow** once.
4. The scheduled workflow will then run daily.

The updater uses public sources and no paid API key. Public website layouts can change, so each source fails independently and keeps the prior values when possible.

## Important backup note

Browser storage is device-specific. Click **Export** periodically and before the draft. Import the JSON file on another device to move your rankings.
