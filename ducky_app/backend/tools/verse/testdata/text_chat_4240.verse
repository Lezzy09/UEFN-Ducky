# Team text chat (UEFN 42.40, compile-verified).
#
# Place team_text_chat_device in the level. Each team gets its own text channel
# ("Team 1", "Team 2", ...) in its own color, with a [Team N] label after names.
# Players join their team's channel when they arrive and leave it when they go.
#
# From your own code:
#   * RefreshAgent(Agent)          after a player changes team
#   * SetCanType(Agent, false)     read-only (they still see the channel and its messages)
#   * SetLabel(Agent, Msg, Color)  a per-player [label] and color, ClearLabel to undo
#   * SetTeamChatEnabled(false)    silence every team channel (round end, cutscene)
#
# Verse can't post, read or filter chat messages: it controls who is in a channel,
# who may type and how messages look. Up to 100 members per channel; parental
# controls and the player's own settings still apply.
using { /Fortnite.com/Devices }
using { /Fortnite.com/Teams }
using { /Verse.org/AgentGroup }
using { /Verse.org/Chat }
using { /Verse.org/Colors }
using { /Verse.org/Simulation }

# A text channel needs a concrete member-info class.
team_text_member<public> := class(has_text_member_info):
    var CanSend<override>:logic = true
    var MessageStyle<override>:?text_message_style = false

TeamChatText<localizes>(Text:string):message = "{Text}"

team_text_chat_device<public> := class(creative_device):
    var Groups:[team]agent_group(team_text_member) = map{}
    var Channels:[team]text_channel(team_text_member) = map{}

    OnBegin<override>()<suspends>:void =
        if (Sim := GetSimulationEntity[]):
            for (Index -> Team : GetPlayspace().GetTeamCollection().GetTeams()):
                Group := agent_group(team_text_member){}
                Label := TeamChatText("Team {Index + 1}")
                Color := ColorFor(Index)
                Channel := text_channel(team_text_member):
                    Name := Label
                    Group := Group
                    MessageStyle := text_message_style{TextColor := Color, ContextMessage := option{Label}}
                    SystemMessageColor := Color
                # AddChatChannel is no_rollback: call it outside the if, then check the result.
                Result := Sim.AddChatChannel(Channel)
                if (Result.GetSuccess[]):
                    if (set Groups[Team] = Group, set Channels[Team] = Channel) {}
        for (Player : GetPlayspace().GetPlayers()):
            RefreshAgent(Player)
        GetPlayspace().PlayerAddedEvent().Subscribe(OnPlayerAdded)
        GetPlayspace().PlayerRemovedEvent().Subscribe(OnPlayerRemoved)

    OnPlayerAdded(Player:player):void =
        RefreshAgent(Player)

    OnPlayerRemoved(Player:player):void =
        for (Group : Groups):
            Group.RemoveMember(Player)

    # Puts the agent in its current team's channel only.
    RefreshAgent<public>(Agent:agent):void =
        for (Group : Groups):
            Group.RemoveMember(Agent)
        if (Team := GetPlayspace().GetTeamCollection().GetTeam[Agent], Group := Groups[Team]):
            Group.AddMember(Agent, team_text_member{})

    # false = read-only: the player still sees the channel and its messages.
    SetCanType<public>(Agent:agent, CanType:logic):void =
        for (Group : Groups, Info := Group.GetMemberMap()[Agent]):
            set Info.CanSend = CanType

    # A per-player label ("Jonesy [Captain]: gg") and color; only new messages change.
    SetLabel<public>(Agent:agent, Label:message, Color:color):void =
        for (Group : Groups, Info := Group.GetMemberMap()[Agent]):
            set Info.MessageStyle = option{text_message_style{TextColor := Color, ContextMessage := option{Label}}}

    ClearLabel<public>(Agent:agent):void =
        for (Group : Groups, Info := Group.GetMemberMap()[Agent]):
            set Info.MessageStyle = false

    SetTeamChatEnabled<public>(Enabled:logic):void =
        for (Channel : Channels):
            if (Enabled?):
                Channel.Enable()
            else:
                Channel.Disable()

    ColorFor(Index:int)<transacts>:color =
        Palette := array{NamedColors.Red, NamedColors.Blue, NamedColors.Green, NamedColors.Yellow}
        if (C := Palette[Mod[Index, Palette.Length]]):
            C
        else:
            NamedColors.White
