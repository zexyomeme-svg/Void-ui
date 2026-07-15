#!/usr/bin/env python3
"""
VOID-NUKE - Command Runner v4 - Multi-threaded - All 39 commands perfected
Fixes audioop, uses ThreadPoolExecutor for MT

Usage:
  python command_runner.py --token TOKEN --guild ID --action nuke --confirm
  python command_runner.py --list
  python run.py --cli --token ... --guild ... --action ban_all --confirm
"""

import sys
try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
        sys.modules['audioop']=audioop
        print("[FIX] audioop-lts shim", flush=True)
    except ImportError:
        import types
        sys.modules['audioop']=types.ModuleType("audioop")

import asyncio, argparse, os, json, threading
from concurrent.futures import ThreadPoolExecutor
import discord
from discord.ext import commands
from bot_manager import manager, log_buffer, REQUIRED_PERMISSIONS, REQUIRED_INTENTS

# Multi-threading executor for CLI bulk ops
threads = int(os.getenv("VOID_THREADS","4"))
cli_executor = ThreadPoolExecutor(max_workers=threads, thread_name_prefix="void-cli")

def parse_extra_args():
    parser=argparse.ArgumentParser(description="VOID-NUKE CLI v4 MT - All 39 cmds perfected")
    parser.add_argument("--token", required=False, help="Bot token")
    parser.add_argument("--guild", required=False, help="Guild ID")
    parser.add_argument("--action", required=False, help="Action ID or name - use --list")
    parser.add_argument("--list", action="store_true", help="List all commands")
    parser.add_argument("--permissions", action="store_true", help="Check permissions after connect")
    parser.add_argument("--confirm", action="store_true", help="Confirm destructive")
    parser.add_argument("--threads", type=int, default=threads, help=f"Thread count (default {threads})")
    args, unknown=parser.parse_known_args()
    params={}
    i=0
    while i < len(unknown):
        if unknown[i].startswith("--"):
            key=unknown[i][2:]
            if i+1 < len(unknown) and not unknown[i+1].startswith("--"):
                val=unknown[i+1]
                try:
                    if "." not in val: params[key]=int(val)
                    else: params[key]=float(val)
                except:
                    if val.lower() in ("true","false"): params[key]=val.lower()=="true"
                    else: params[key]=val
                i+=2
            else:
                params[key]=True; i+=1
        else: i+=1
    if args.confirm: params["confirm"]=True
    params["threads"]=args.threads
    return args, params

def print_commands():
    print(f"""
VOID-NUKE v4 - All 39 Original Commands - Multi-threaded Perfected
Threads: {threads} workers | Audioop fix | Chunked gather
====================================================================
01 - Nuke               | Full nuke: del ch/roles + create raid + webhook spam [MT]
02 - Auto Raid          | Auto raid from config [MT]
03 - Ban All            | Ban all members [MT - Semaphore 5 + chunk 10]
04 - Kick All           | Kick all members [MT]
05 - Mute All           | Timeout all --minutes 60 [MT]
06 - Unban All          | Unban all [MT]
07 - Del Channels        | Delete all channels [MT]
08 - Del Emojis          | Delete all emojis [MT]
09 - Del Stickers        | Delete all stickers [MT]
10 - Create Channels    | Mass create --quantity 10 --type text/voice --name raid [MT]
11 - Create Roles       | Mass create roles --quantity 10 --name VOID [MT]
12 - Create Cats        | Create categories --quantity 5 [MT]
13 - Rename Channels    | Rename all channels --name new [MT]
14 - Rename Roles       | Rename all roles --name new [MT]
15 - Edit Server        | Edit server --name "new" --description "desc" --icon_url url [MT blocking IO offloaded]
16 - Rename Members     | Rename all nicks --name VOID [MT]
17 - Fix Nicks          | Dehoist -- multi-threaded gather
18 - Get Admin          | Create admin role --user_id blank=all [MT]
19 - Impersonate        | Send as user via webhook --target_id ID --message hi [MT]
20 - Ghost Ping         | Ghost ping all [MT]
21 - Remov Roles/Strip  | Remove all roles [MT]
22 - Message All/DM All | DM all --content "hi" [MT]
23 - DM Spam User       | Spam DM user --user_id ID --count 5 [MT]
24 - Webhook Spam       | Webhook spam --count 2 --content "hi" [MT + cleanup]
25 - Server Info        | Show server info + perms
26 - Clone Server       | Clone to JSON [MT file IO offloaded]
27 - Webhook Logs       | Log msgs to webhook --webhook_url url
28 - Lockdown           | Lock all text channels [MT]
29 - Sourdine VC        | Deafen all in VC [MT]
30 - Kick VC All        | Disconnect all VC [MT]
31 - Move All VC        | Move all VC to one --target_id VC_ID [MT]
32 - Invite Spam        | Create invite spam --count 5 [MT]
33 - Spam              | Spam all channels --count 3 --content "hi" [MT]
34 - Thread Spam        | Thread spam --count 2 --name VOID [MT]
35 - Reaction Spam      | Reaction spam --limit 5 [MT]
36 - Voice Spam        | Join/leave VC spam --loops 2 [MT voice]
37 - Spoiler Spam       | Spoiler spam --count 2 --content "VOID" [MT]
38 - Poll Spam          | Poll spam --count 2 --question "Join?" [MT]
39 - Event Spam         | Event spam --count 3 [MT]

Multi-threading: {threads} workers, Semaphore 5, chunk 10, GC after chunk, blocking IO offloaded
Required Intents: Server Members Intent=ON, Message Content=ON (Dev Portal > Bot)
Required Perms: Administrator best, else Ban, Kick, Manage Channels/Roles/Guild/Webhooks/Emojis, etc
Use --permissions to check

Examples:
  python command_runner.py --token TOKEN --guild ID --action server_info
  python command_runner.py --token TOKEN --guild ID --action ban_all --confirm
  python command_runner.py --token TOKEN --guild ID --action nuke --num_channels 30 --confirm --threads 4
  python run.py --cli --token TOKEN --guild ID --action permissions --threads 4
""")

async def main():
    global threads
    args, params = parse_extra_args()
    threads = params.pop("threads", threads)

    if args.list:
        print_commands()
        return

    token=args.token or os.getenv("BOT_TOKEN") or input("Bot Token: ").strip()
    guild_id=args.guild or os.getenv("GUILD_ID") or input("Guild ID: ").strip()
    action=args.action or ""

    if not token or not guild_id:
        print("[ERR] Token and Guild ID required --list for help")
        return

    if not action and not args.permissions:
        print("[INFO] No action, default server_info + permissions")
        action="server_info"
        args.permissions=True

    action_map={
        "01":"nuke","02":"auto_raid","03":"ban_all","04":"kick_all","05":"mute_all",
        "06":"unban_all","07":"delete_channels","08":"delete_emojis","09":"delete_stickers",
        "10":"create_channels","11":"create_roles","12":"create_cats","13":"rename_channels",
        "14":"rename_roles","15":"edit_server","16":"rename_members","17":"fix_nicks",
        "18":"get_admin","19":"impersonate","20":"ghost_ping","21":"strip_roles",
        "22":"dm_all","23":"dm_spam_user","24":"webhook_spam","25":"server_info",
        "26":"clone_server","27":"webhook_logger","28":"lockdown","29":"deafen_all",
        "30":"disconnect_all","31":"mass_move","32":"invite_spam","33":"spam",
        "34":"thread_spam","35":"reaction_spam","36":"vc_spam","37":"spoiler_spam",
        "38":"poll_spam","39":"event_spam",
    }
    action_key=action_map.get(action, action) if action else ""

    intents=discord.Intents.none()
    intents.guilds=True; intents.members=True; intents.bans=True; intents.emojis=True
    intents.voice_states=True; intents.messages=True; intents.message_content=True
    bot=commands.Bot(command_prefix='!', intents=intents, max_messages=None, chunk_guilds_at_startup=False)

    @bot.event
    async def on_ready():
        print(f"[OK] Bot {bot.user} | Threads active {threading.active_count()} | Executor {threads} workers | Main thread {threading.current_thread().name}")
        print(f"[OK] Connected to {len(bot.guilds)} guilds (MT mode)")
        g=bot.get_guild(int(guild_id))
        if not g:
            print(f"[ERR] Guild {guild_id} not found. In:")
            for gg in bot.guilds: print(f"  - {gg.name} ({gg.id})")
            await bot.close(); return
        print(f"[OK] Target {g.name} ({g.id}) {g.member_count} members {len(g.channels)} ch [MT ready]")

        manager.bot=bot; manager.guild_id=guild_id; manager.connected=True
        manager.guild_info={"name":g.name,"id":str(g.id),"members":g.member_count,"channels":len(g.channels),"roles":len(g.roles)}

        if args.permissions or action_key=="permissions":
            print("\n=== PERMS CHECK MT ===")
            perm_check=manager.check_permissions()
            if "error" in perm_check: print(f"[ERR] {perm_check['error']}")
            else:
                print(f"Bot {perm_check['bot_name']} Top {perm_check['top_role']} pos {perm_check['top_role_pos']} Admin {perm_check['is_admin']} AllOk {perm_check['all_ok']}")
                print(f"Active threads {threading.active_count()} tasks {perm_check.get('active_tasks')}")
                for k,v in perm_check["permissions"].items():
                    print(f"  {'✅' if v['has'] else '❌'} {v['name']}: {v['desc']} for {', '.join(v['needed_for'])}")
                for k,v in perm_check["intents"].items():
                    print(f"  {'✅' if v['has'] else '❌'} Intent {v['name']}")
            print("=== END PERMS ===\n")
            if action_key=="permissions" or not action:
                await bot.close(); return

        if action_key:
            print(f"\n[RUN MT] {action_key} params {params} threads {threads}")
            destructive={"nuke","ban_all","kick_all","delete_channels","auto_raid"}
            if action_key in destructive and not params.get("confirm"):
                print(f"[ERR] {action_key} needs --confirm"); await bot.close(); return
            func=manager.ACTIONS.get(action_key)
            if not func:
                print(f"[ERR] Unknown {action_key} --list"); await bot.close(); return
            try:
                # Run with threading info
                start=time.time() if 'time' in dir() else 0
                import time as _time
                start=_time.time()
                result=await func(manager, params)
                elapsed=_time.time()-start
                print(f"[OK MT] {action_key} done in {elapsed:.2f}s result {result} | Threads now {threading.active_count()}")
            except Exception as e:
                import traceback
                print(f"[ERR] {e}"); traceback.print_exc()
        await bot.close()

    try: await bot.start(token)
    except discord.LoginFailure: print("[ERR] Invalid token")
    except Exception as e: print(f"[ERR] {e}")
    finally: cli_executor.shutdown(wait=False)

if __name__=="__main__":
    import time
    asyncio.run(main())
