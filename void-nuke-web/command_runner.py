#!/usr/bin/env python3
"""
VOID-NUKE - Command Runner (Standalone CLI)
Full 39 commands from https://github.com/v0id4real/Void-Nuke
Uses same bot_manager core as web UI, but CLI for direct execution.

Fixes audioop for Python 3.13.

Usage:
  python command_runner.py --token YOUR_TOKEN --guild 123456789 --action nuke --confirm
  python command_runner.py --token ... --guild ... --action ban_all --confirm
  python command_runner.py --token ... --guild ... --list
  python command_runner.py --token ... --guild ... --action create_channels --quantity 10 --type text --name raid
  python command_runner.py --token ... --guild ... --action spam --count 3 --content "@everyone hi"
  python command_runner.py --token ... --guild ... --action permissions

All original commands supported:
 01 Nuke, 02 Auto Raid, 03 Ban All, 04 Kick All, 05 Mute All, 06 Unban All,
 07 Del Channels, 08 Del Emojis, 09 Del Stickers, 10 Create Channels, 11 Create Roles,
 12 Create Cats, 13 Rename Channels, 14 Rename Roles, 15 Edit Server, 16 Rename Members,
 17 Fix Nicks, 18 Get Admin, 19 Impersonate, 20 Ghost Ping, 21 Strip Roles, 22 Message All,
 23 DM Spam User, 24 Webhook Spam, 25 Server Info, 26 Clone Server, 27 Webhook Logs,
 28 Lockdown, 29 Sourdine VC, 30 Kick VC All, 31 Move All VC, 32 Invite Spam, 33 Spam,
 34 Thread Spam, 35 Reaction Spam, 36 Voice Spam, 37 Spoiler Spam, 38 Poll Spam, 39 Event Spam
"""

# audioop fix MUST be first
import sys
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop'] = audioop
        print("[FIX] audioop -> audioop-lts shim")
    except ImportError:
        import types
        sys.modules['audioop'] = types.ModuleType("audioop")

import asyncio
import argparse
import os
import json
import discord
from discord.ext import commands

# Import our core
from bot_manager import manager, log_buffer, REQUIRED_PERMISSIONS, REQUIRED_INTENTS
# Import all command funcs via manager.ACTIONS

def parse_extra_args():
    """Parse unknown args as --key value for params"""
    parser = argparse.ArgumentParser(description="VOID-NUKE Command Runner - All 39 commands")
    parser.add_argument("--token", required=False, help="Bot token")
    parser.add_argument("--guild", required=False, help="Guild ID (server ID)")
    parser.add_argument("--action", required=False, help="Action ID or name (e.g., nuke, ban_all, 01, 03...) - use --list to see all")
    parser.add_argument("--list", action="store_true", help="List all commands")
    parser.add_argument("--permissions", action="store_true", help="Check bot permissions after connect")
    parser.add_argument("--confirm", action="store_true", help="Confirm destructive actions (nuke, ban_all, etc)")
    args, unknown = parser.parse_known_args()
    
    # Parse unknown as params: --quantity 10 --name foo etc
    params = {}
    i = 0
    while i < len(unknown):
        if unknown[i].startswith("--"):
            key = unknown[i][2:]
            if i+1 < len(unknown) and not unknown[i+1].startswith("--"):
                val = unknown[i+1]
                # Try int conversion
                try:
                    if "." not in val:
                        params[key] = int(val)
                    else:
                        params[key] = float(val)
                except:
                    # Handle bool strings
                    if val.lower() in ("true","false"):
                        params[key] = val.lower() == "true"
                    else:
                        params[key] = val
                i += 2
            else:
                params[key] = True
                i += 1
        else:
            i += 1

    if args.confirm:
        params["confirm"] = True

    return args, params

def print_commands():
    print("""
VOID-NUKE - All 39 Original Commands
=====================================
01 - Nuke               | Full nuke: del ch/roles + create raid + webhook spam
02 - Auto Raid          | Auto raid from config
03 - Ban All            | Ban all members
04 - Kick All           | Kick all members
05 - Mute All           | Timeout all (--minutes 60)
06 - Unban All          | Unban all
07 - Del Channels        | Delete all channels
08 - Del Emojis          | Delete all emojis
09 - Del Stickers        | Delete all stickers
10 - Create Channels    | Mass create ch (--quantity 10 --type text/voice --name raid)
11 - Create Roles       | Mass create roles (--quantity 10 --name VOID)
12 - Create Cats        | Create categories (--quantity 5 --name VOID)
13 - Rename Channels    | Rename all channels (--name newname)
14 - Rename Roles       | Rename all roles (--name newname)
15 - Edit Server        | Edit server (--name "new" --description "desc" --icon_url url)
16 - Rename Members     | Rename all nicks (--name VOID)
17 - Fix Nicks          | Dehoist nicks (Fix Nicks)
18 - Get Admin          | Create admin role (--user_id blank=all or specific ID)
19 - Impersonate        | Send as user via webhook (--target_id ID --message hi --channel_id optional)
20 - Ghost Ping         | Ghost ping all members
21 - Remov Roles / Strip Roles | Remove all roles from members
22 - Message All / DM All | DM all members (--content "hi")
23 - DM Spam User       | Spam DM user (--user_id ID --count 5 --content hi)
24 - Webhook Spam       | Webhook spam (--count 2 --content "hi" or embed)
25 - Server Info        | Show server info
26 - Clone Server       | Clone to clone_<id>.json
27 - Webhook Logs       | Log msgs to webhook (--webhook_url url)
28 - Lockdown           | Lock all text channels
29 - Sourdine VC        | Deafen all in VC
30 - Kick VC All        | Disconnect all VC
31 - Move All VC        | Move all VC to one (--target_id VC_ID)
32 - Invite Spam        | Create invite spam (--count 5)
33 - Spam              | Spam all channels (--count 3 --content "hi" or embed)
34 - Thread Spam        | Thread spam (--count 2 --name VOID)
35 - Reaction Spam      | Reaction spam (--limit 5)
36 - Voice Spam / VC Spam | Join/leave VC spam (--loops 2)
37 - Spoiler Spam       | Spoiler spam (--count 2 --content "VOID")
38 - Poll Spam          | Poll spam (--count 2 --question "Join?")
39 - Event Spam         | Event spam (--count 3 --name VOID --description "raid")

Required Intents (Discord Dev Portal > Bot):
  - Server Members Intent: ON (required)
  - Message Content Intent: ON (required)

Required Permissions (invite with Administrator for all):
  - Administrator, Ban Members, Kick Members, Manage Channels, Manage Roles,
    Manage Guild, Manage Messages, Manage Emojis/Stickers, Moderate Members,
    Manage Webhooks, Create Invite, Send Messages, Move Members, Mute Members

Examples:
  python command_runner.py --token TOKEN --guild GUILD_ID --action server_info
  python command_runner.py --token TOKEN --guild GUILD_ID --action ban_all --confirm
  python command_runner.py --token TOKEN --guild GUILD_ID --action create_channels --quantity 10 --name raid-by-void
  python command_runner.py --token TOKEN --guild GUILD_ID --action spam --count 3 --content "@everyone RAID"
  python command_runner.py --token TOKEN --guild GUILD_ID --permissions
""")

async def main():
    args, params = parse_extra_args()

    if args.list:
        print_commands()
        return

    token = args.token or os.getenv("BOT_TOKEN") or input("Bot Token: ").strip()
    guild_id = args.guild or os.getenv("GUILD_ID") or input("Server ID (Guild ID): ").strip()
    action = args.action or ""

    if not token or not guild_id:
        print("[ERR] Token and Guild ID required")
        print("Use --list to see commands, or --help")
        return

    if not action and not args.permissions:
        print("[INFO] No action specified, defaulting to server_info + permissions")
        action = "server_info"
        args.permissions = True

    # Map numeric to names (same as app.py)
    action_map = {
        "01": "nuke", "02": "auto_raid", "03": "ban_all", "04": "kick_all", "05": "mute_all",
        "06": "unban_all", "07": "delete_channels", "08": "delete_emojis", "09": "delete_stickers",
        "10": "create_channels", "11": "create_roles", "12": "create_cats", "13": "rename_channels",
        "14": "rename_roles", "15": "edit_server", "16": "rename_members", "17": "fix_nicks",
        "18": "get_admin", "19": "impersonate", "20": "ghost_ping", "21": "strip_roles",
        "22": "dm_all", "23": "dm_spam_user", "24": "webhook_spam", "25": "server_info",
        "26": "clone_server", "27": "webhook_logger", "28": "lockdown", "29": "deafen_all",
        "30": "disconnect_all", "31": "mass_move", "32": "invite_spam", "33": "spam",
        "34": "thread_spam", "35": "reaction_spam", "36": "vc_spam", "37": "spoiler_spam",
        "38": "poll_spam", "39": "event_spam",
    }

    # Normalize action
    action_key = action_map.get(action, action) if action else ""
    
    # Create bot
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    intents.bans = True
    intents.emojis = True
    intents.voice_states = True
    intents.messages = True
    intents.message_content = True

    bot = commands.Bot(command_prefix='!', intents=intents, max_messages=None, chunk_guilds_at_startup=False)

    @bot.event
    async def on_ready():
        print(f"[OK] Bot ready as {bot.user}")
        print(f"[OK] Connected to {len(bot.guilds)} guild(s)")
        g = bot.get_guild(int(guild_id))
        if not g:
            print(f"[ERR] Guild {guild_id} not found. Bot is in:")
            for gg in bot.guilds:
                print(f"  - {gg.name} ({gg.id})")
            await bot.close()
            return

        print(f"[OK] Target guild: {g.name} ({g.id}) - {g.member_count} members, {len(g.channels)} channels")

        # Set manager globals for permissions check
        manager.bot = bot
        manager.guild_id = guild_id
        manager.connected = True
        manager.guild_info = {"name": g.name, "id": str(g.id), "members": g.member_count, "channels": len(g.channels), "roles": len(g.roles)}

        # Permissions check
        if args.permissions or action_key == "permissions":
            print("\n=== PERMISSIONS CHECK ===")
            perm_check = manager.check_permissions()
            if "error" in perm_check:
                print(f"[ERR] {perm_check['error']}")
            else:
                print(f"Bot: {perm_check['bot_name']} ({perm_check['bot_id']})")
                print(f"Top Role: {perm_check['top_role']} (pos {perm_check['top_role_pos']})")
                print(f"Is Admin: {perm_check['is_admin']}")
                print(f"All Perms OK: {perm_check['all_ok']}")
                print("\nPermissions:")
                for k, v in perm_check["permissions"].items():
                    status = "✅" if v["has"] else "❌"
                    bypass = " (admin bypass)" if v.get("is_admin_bypass") else ""
                    print(f"  {status} {v['name']}: {v['desc']} - needed for {', '.join(v['needed_for'])}{bypass}")
                print("\nIntents:")
                for k, v in perm_check["intents"].items():
                    status = "✅" if v["has"] else "❌"
                    req = "REQUIRED" if v["required"] else "optional"
                    print(f"  {status} {v['name']} ({req}): {v['desc']}")
                print("\nHow to fix missing permissions:")
                print("  1. Go to https://discord.com/developers/applications -> your bot -> Bot")
                print("  2. Enable Server Members Intent + Message Content Intent")
                print("  3. OAuth2 -> URL Generator -> bot + applications.commands, Administrator")
                print(f"  4. Invite example: https://discord.com/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot%20applications.commands")
                print("  5. Ensure bot role is ABOVE other roles in Server Settings -> Roles")
                print("=== END PERMISSIONS ===\n")

            if action_key == "permissions" or not action:
                await bot.close()
                return

        # Run action if specified
        if action_key:
            print(f"\n[RUN] Action: {action_key} with params {params}")
            # Check destructive
            destructive = {"nuke", "ban_all", "kick_all", "delete_channels", "auto_raid"}
            if action_key in destructive and not params.get("confirm"):
                print(f"[ERR] Action '{action_key}' is destructive and requires --confirm")
                print(f"      Run with --confirm flag: --action {action_key} --confirm")
                await bot.close()
                return

            func = manager.ACTIONS.get(action_key)
            if not func:
                print(f"[ERR] Unknown action '{action_key}'. Use --list")
                await bot.close()
                return

            try:
                # Inject bot/manager loop already set
                result = await func(manager, params)
                print(f"[OK] Action {action_key} completed. Result: {result}")
            except Exception as e:
                import traceback
                print(f"[ERR] Action failed: {e}")
                traceback.print_exc()

        await bot.close()

    try:
        await bot.start(token)
    except discord.LoginFailure:
        print("[ERR] Invalid token")
    except Exception as e:
        print(f"[ERR] Bot error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
