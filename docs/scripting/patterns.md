# Common field script patterns

Recipes for the things you actually write. Every snippet here is the shape used
by the vanilla scripts, so when in doubt, copying one of these and renaming is
the safe move. See [README.md](README.md) for how a script file is structured
and wired into the build, and [command_reference.md](command_reference.md) for
the full command list.

## The golden rule: lock, act, release

Anything that takes control away from the player must give it back on **every**
path out. A script that hits `End` without a matching `ReleaseAll` leaves the
game frozen, and this is by far the most common way to break a map.

```asm
MyMap_Talker:
    PlaySE SE_CONFIRM_sseq_3     @ the "someone is talking" blip
    LockAll                      @ freeze player and NPCs
    FacePlayer                   @ turn the NPC toward the player
    Message MyMap_Text_Hello
    WaitButton
    CloseMessage
    ReleaseAll                   @ hand control back
    End
```

Because that block is written hundreds of times, there is a macro for it:

```asm
MyMap_Talker:
    NPCMessage MyMap_Text_Hello
    End
```

`NPCMessage` expands to exactly the seven commands above. `EventMessage` is the
same without `FacePlayer`, for signs and objects that have no facing.

## Dialogue that branches on progress

The idiom is: check state first, `GoTo` a labelled branch, and let each branch
close out on its own. Note that each branch ends with `CloseMessage` +
`ReleaseAll` + `End` - the `GoTo` does not come back.

```asm
MyMap_Villager:
    PlaySE SE_CONFIRM_sseq_3
    LockAll
    FacePlayer
    GoToIfSet FLAG_HAS_POKEDEX, MyMap_VillagerAfterDex
    GoToIfGe VAR_MY_QUEST_STATE, 2, MyMap_VillagerMidQuest
    Message MyMap_Text_VillagerIntro
    WaitButton
    CloseMessage
    ReleaseAll
    End

MyMap_VillagerMidQuest:
    Message MyMap_Text_VillagerMidQuest
    WaitButton
    CloseMessage
    ReleaseAll
    End

MyMap_VillagerAfterDex:
    Message MyMap_Text_VillagerAfterDex
    WaitButton
    CloseMessage
    ReleaseAll
    End
```

Conditionals come in `GoToIf*` and `CallIf*` pairs. `GoToIf*` jumps and never
returns; `CallIf*` runs a subroutine that ends in `Return` and continues from
the next line - use it when several conditions each contribute a side effect:

```asm
MyMap_OnTransition:
    CallIfEq VAR_MY_QUEST_STATE, 4, MyMap_AdvanceToState5
    CallIfEq VAR_MY_QUEST_STATE, 6, MyMap_AdvanceToState7
    End

MyMap_AdvanceToState5:
    SetVar VAR_MY_QUEST_STATE, 5
    Return
```

Comparison suffixes are `Eq`, `Ne`, `Lt`, `Le`, `Gt`, `Ge` for vars, and
`Set`/`Unset` for flags: `GoToIfEq`, `CallIfNe`, `GoToIfSet`, `CallIfUnset`.

## Yes/no question

`ShowYesNoMenu` writes `MENU_YES` or `MENU_NO` into the var you pass, which is
almost always `VAR_RESULT`.

```asm
MyMap_AskToHeal:
    PlaySE SE_CONFIRM_sseq_3
    LockAll
    FacePlayer
    Message MyMap_Text_WouldYouLikeToRest
    ShowYesNoMenu VAR_RESULT
    GoToIfEq VAR_RESULT, MENU_NO, MyMap_Declined
    Message MyMap_Text_RestWell
    WaitButton
    CloseMessage
    ReleaseAll
    End

MyMap_Declined:
    Message MyMap_Text_MaybeNextTime
    WaitButton
    CloseMessage
    ReleaseAll
    End
```

## Giving an item

Items go through the common script at `Common_GiveItemQuantity`, which reads the
item from `VAR_0x8004` and the quantity from `VAR_0x8005` and prints the
"obtained" message itself. Always guard it with `GoToIfCannotFitItem`, and
always set a flag so the NPC cannot be farmed.

```asm
MyMap_ItemGiver:
    PlaySE SE_CONFIRM_sseq_3
    LockAll
    FacePlayer
    GoToIfSet FLAG_RECEIVED_MY_MAP_POTION, MyMap_ItemGiverAfter
    Message MyMap_Text_HereTakeThis
    SetVar VAR_0x8004, ITEM_SUPER_POTION
    SetVar VAR_0x8005, 1
    GoToIfCannotFitItem VAR_0x8004, VAR_0x8005, VAR_RESULT, MyMap_BagIsFull
    Common_GiveItemQuantity
    SetFlag FLAG_RECEIVED_MY_MAP_POTION
    GoTo MyMap_ItemGiverAfter
    End

MyMap_ItemGiverAfter:
    Message MyMap_Text_UseItWell
    WaitButton
    CloseMessage
    ReleaseAll
    End

MyMap_BagIsFull:
    Common_MessageBagIsFull
    CloseMessage
    ReleaseAll
    End
```

## Giving a Pokémon

`GivePokemon` writes a success code into the var you pass; check it before
celebrating. Check the party count first if you want the "party is full"
message rather than a silent send-to-box.

```asm
MyMap_GiveStarter:
    GetPartyCount VAR_RESULT
    GoToIfGe VAR_RESULT, 6, MyMap_PartyIsFull
    GivePokemon SPECIES_EEVEE, 5, ITEM_NONE, VAR_RESULT
    PlayFanfare SEQ_FANFA4_sseq
    WaitFanfare
    Message MyMap_Text_YouGotAnEevee
    WaitButton
    CloseMessage
    ReleaseAll
    End
```

## A bespoke trainer battle

Ordinary route trainers need no script at all - set `trainer_type` to
`TRAINER_TYPE_NORMAL` in `events_*.json` and put the `TRAINER_*` constant in
`script`. Write a script only when the battle is part of a scene:

```asm
MyMap_Leader:
    PlaySE SE_CONFIRM_sseq_3
    LockAll
    FacePlayer
    GoToIfBadgeAcquired BADGE_ID_MINE, MyMap_LeaderAfterBadge
    Message MyMap_Text_LeaderIntro
    CloseMessage
    StartTrainerBattle TRAINER_LEADER_BYRON
    CheckWonBattle VAR_RESULT
    GoToIfEq VAR_RESULT, FALSE, MyMap_LostBattle
    Message MyMap_Text_YouWin
    PlayFanfare SEQ_BADGE_sseq
    WaitFanfare
    GiveBadge BADGE_ID_MINE
    SetFlag FLAG_MY_MAP_LEADER_DEFEATED
    CloseMessage
    ReleaseAll
    End

MyMap_LostBattle:
    BlackOutFromBattle
    ReleaseAll
    End
```

`CheckWonBattle` is mandatory: after a loss the script keeps running, so without
the branch the player gets the victory dialogue anyway.

## Movement and cutscenes

`ApplyMovement` queues a movement block on one object and returns immediately;
`WaitMovement` blocks until every queued block has finished. Queue all the
actors first, then wait once, so they move together.

```asm
MyMap_CoordEvent_Ambush:
    LockAll
    ApplyMovement LOCALID_RIVAL, MyMap_Movement_RivalNoticePlayer
    ApplyMovement LOCALID_PLAYER, MyMap_Movement_PlayerTurnAround
    WaitMovement
    Message MyMap_Text_ThereYouAre
    WaitButton
    CloseMessage
    ApplyMovement LOCALID_RIVAL, MyMap_Movement_RivalLeave
    WaitMovement
    RemoveObject LOCALID_RIVAL
    SetVar VAR_MY_CUTSCENE_STATE, 1
    ReleaseAll
    End

    .balign 4, 0
MyMap_Movement_RivalNoticePlayer:
    WalkOnSpotFastSouth
    EmoteExclamationMark
    Delay8
    WalkNormalSouth 3
    EndMovement

    .balign 4, 0
MyMap_Movement_RivalLeave:
    WalkFastNorth 4
    SetInvisible
    EndMovement
```

Points worth internalising:

- `LOCALID_PLAYER` moves the player; `LOCALID_CAMERA` (via
  `ApplyFreeCameraMovement`) moves the camera.
- Every movement block needs `.balign 4, 0` before its label and `EndMovement`
  after its last action.
- Movement actions take an optional repeat count: `WalkNormalSouth 3`.
- `AddObject` / `RemoveObject` show and hide an object for the rest of the map
  visit; to make the change stick across a reload, set the object's
  `hidden_flag` in `events_*.json` and toggle that flag instead.

### Reacting to where the player is standing

A coord event fires over a rectangle, so a cutscene that must line actors up
exactly reads the player's tile and branches. This is why vanilla scripts have
those long `GoToIfEq VAR_0x8004, 108, ...` ladders.

```asm
MyMap_CoordEvent_Stop:
    LockAll
    GetPlayerMapPos VAR_0x8004, VAR_0x8005    @ x into 8004, z into 8005
    GoToIfEq VAR_0x8004, 108, MyMap_StopAtX108
    GoTo MyMap_StopAtX109
```

`GetPlayerDir VAR_RESULT` does the same for facing, returning `DIR_NORTH`,
`DIR_SOUTH`, `DIR_EAST` or `DIR_WEST`.

## Fading and warping

```asm
MyMap_EnterCave:
    LockAll
    FadeScreenOut
    WaitFadeScreen
    Warp MAP_HEADER_MY_CAVE, 12, 30, DIR_NORTH
    FadeScreenIn
    WaitFadeScreen
    ReleaseAll
    End
```

`FadeScreenOut` / `FadeScreenIn` both take optional `frames` and `color`
arguments (`FadeScreenOut FADE_SCREEN_SPEED_SLOW, COLOR_WHITE`). Each must be
followed by `WaitFadeScreen` before anything else happens, or the fade and the
next command race.

Most doors and stairs do not need a script at all - a `warp_events` entry in
`events_*.json` handles them.

## Signs

```asm
MyMap_ArrowSign:
    ShowArrowSign MyMap_Text_ToOreburgh
    End

MyMap_TrainerTips:
    ShowScrollingSign MyMap_Text_TrainerTipsPotions
    End
```

`ShowMapSign`, `ShowArrowSign`, `ShowLandmarkSign` and `ShowScrollingSign` each
handle their own window lifecycle, so no `LockAll` / `ReleaseAll` is needed.
Plain wall signs and bookshelves usually don't need a script either - point the
`bg_events` entry at the shared `scripts_bg_events` file instead.

## A map-load hook

`OnTransition` scripts run before the map is drawn, so they can move objects and
set state without the player seeing it. They get no `LockAll` and must not show
messages.

```asm
    ScriptEntry MyMap_OnTransition       @ entry 1
    ScriptEntryEnd

MyMap_OnTransition:
    CallIfSet FLAG_MY_QUEST_DONE, MyMap_HideQuestGiver
    End

MyMap_HideQuestGiver:
    SetObjectEventPos LOCALID_QUEST_GIVER, 20, 40
    Return
```

Hook it up in `scripts_init_my_map.s`:

```asm
#include "macros/scrcmd.inc"


    InitScriptEntry_OnTransition 1
    InitScriptEntryEnd

    InitScriptEnd
```

## Sound

```asm
    PlaySE SE_CONFIRM_sseq_3          @ a one-shot effect
    WaitSE SE_CONFIRM_sseq_3          @ block until it finishes
    PlayFanfare SEQ_FANFA4_sseq       @ a jingle over the music
    WaitFanfare
    PlayCry SPECIES_EEVEE, 0
    WaitCry
```

`Common_SetRivalBGM` and the matching `Common_FadeToDefaultMusic` swap the map
music for a scene and put it back.

## Mistakes that cost the most time

- **Inserting a `ScriptEntry` in the middle of the table.** Every index after it
  shifts, silently rewiring every NPC on the map. Append.
- **A path that reaches `End` without `ReleaseAll`.** The game hangs. Check
  every branch, including the loss branch of a battle.
- **Forgetting `WaitMovement` after `ApplyMovement`.** The script runs on while
  the actor is still walking.
- **`Message` without `WaitButton` / `CloseMessage`.** The box stays up, or the
  next command draws over it.
- **Off-by-one on script indices.** The entry table is 1-based, so the first
  `ScriptEntry` is script `1`. Both `0` and `65535` mean "no script".
- **Assuming `VAR_0x8000`-`VAR_0x800D` persist.** They are scratch, and common
  scripts clobber them. Anything that must survive the map needs its own var.
