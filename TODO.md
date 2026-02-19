# NoteHelper TODO

## Production Setup

### Configure Auto-Start at Boot
Once you have your Windows password, run this in an elevated PowerShell:

```powershell
schtasks /create /tn "NoteHelper" /tr "C:\prod\NoteHelper\start_prod.bat" /sc onstart /ru "northamerica\alexbla" /rl highest /rp "YourPassword" /f
```

This stores credentials so the server runs hidden as your user at boot, with MSX auth working.

**Current workaround:** Run `C:\prod\NoteHelper\deploy.ps1` manually (StreamDeck button) which starts the server hidden if not running.

---

## MSX Integration Enhancements

### Automate Data Pull from MSX
Use MSX APIs to automatically sync data instead of manual entry:

- **Territories** - Pull territory assignments from MSX
- **Customers** - Sync customer accounts and TPIDs from MSX
- **Sellers** - Import seller/account team data from MSX
- **Pods** - Pull pod/team structure from MSX

This would reduce manual data entry and keep NoteHelper in sync with MSX assignments.

**Relevant MSX entities to explore:**
- `accounts` - Customer accounts with TPIDs
- `systemusers` - Sellers and their assignments
- `teams` - Pod/team structures
- `territories` - Territory definitions

---

## Feature Ideas

- [ ] Bulk milestone selection for call logs
- [ ] MSX task templates (pre-fill common task patterns)
- [ ] Dashboard widget showing MSX connection status
- [ ] Auto-refresh token before expiry warning
