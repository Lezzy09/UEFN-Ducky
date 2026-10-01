using { /Fortnite.com/AI }
using { /Fortnite.com/Playspaces }
using { /UnrealEngine.com/Conversations }
using { /UnrealEngine.com/Temporary/Diagnostics }
using { /Verse.org/AgentGroup }
using { /Verse.org/Chat }
using { /Verse.org/SceneGraph }
using { /Verse.org/Simulation }

ducky_check_log<public> := class(log_channel){}

# Each voice channel needs a concrete member-info class.
ducky_check_member<public> := class(has_voice_member_info){}

ducky_check_mood<public> := enum:
    Happy
    Annoyed

# Structured output: the model fills these fields; @ai_description tells it how.
ducky_check_offer<public> := struct:
    @ai_description("True when you and the player agreed on a price you are both happy with.")
    Accepted:logic = false
    @ai_description("The agreed price in gold.")
    Price:int = 0

ducky_check_read<public> := struct:
    @ai_description("How you feel about the player right now.")
    Mood:ducky_check_mood = ducky_check_mood.Happy
    @ai_description("How many times the player has spoken to you.")
    Count:int = 0

DuckyCheckText<localizes>(Text:string):message = "{Text}"

ducky_check_npc<public> := class(npc_behavior):
    Logger:log = log{Channel := ducky_check_log}
    var MaybeChannel:?voice_channel(ducky_check_member) = false
    var Cancels:[]cancelable = array{}

    OnBegin<override>()<suspends>:void =
        if:
            Entity := GetEntity[]
            NPCAgent := GetAgent[]
            Persona := Entity.GetComponent[persona_component]
            Sim := Entity.GetSimulationEntity[]
        then:
            # 1. A voice channel with the NPC and the players in it.
            Group := agent_group(ducky_check_member){}
            Channel := voice_channel(ducky_check_member){Name := DuckyCheckText("Shop"), Group := Group}
            set MaybeChannel = option{Channel}
            Sim.AddChatChannel(Channel)
            Group.AddMember(NPCAgent, ducky_check_member{CanBroadcast := true})
            if (Playspace := Entity.GetPlayspaceForEntity[]):
                for (Player : Playspace.GetPlayers()):
                    Group.AddMember(Player, ducky_check_member{CanBroadcast := true})
                    Player.SetConversationTarget(Persona, Channel)
            # 2. Who the NPC is (replaces the editor prompt; Personality is read-only).
            # <localizes> calls are no_rollback: build messages BEFORE a [ ] call (else E3512).
            Personality := DuckyCheckText("You are a grumpy car buyer with a budget of 500 gold. Keep replies under 20 words.")
            if (Persona.SetPersonality[Personality]) {}
            if (Persona.SetVoice[guild_voice{}]) {}
            set Persona.PromptInterruptionRule = persona_interruption_rule.InterruptOnPromptStart
            # 3. Structured output the model may emit alongside any reply.
            Session := Persona.GetAISession()
            OfferDef := prompt_binding_definition:
                Name := DuckyCheckText("FinalOffer")
                Description := DuckyCheckText("Signals when you and the player agreed on a price.")
            set Cancels += array{Session.RegisterAction(OfferDef, false, ducky_check_offer, OnOffer)}
            # 4. Captions and failures.
            set Cancels += array{Persona.CommitSayEvent.Subscribe(OnSaid)}
            set Cancels += array{Persona.StopSayEvent.Subscribe(OnStopped)}
            set Cancels += array{Persona.PromptFailureEvent.Subscribe(OnFailed)}
            # 5. Make the NPC speak first.
            Greeting := DuckyCheckText("Greet the player who just walked in.")
            if (Persona.PromptToTalk[Greeting, Channel]) {}
            # 6. A one-shot structured question (no speech).
            Reply := Session.Prompt(DuckyCheckText("Rate the player so far."), ducky_check_read)
            if (Read := Reply.GetSuccess[]):
                Logger.Print("Mood count {Read.Count}")
            else if (Error := Reply.GetError[], ai_throttled_error[Error]):
                Logger.Print("Throttled; try later")

    OnOffer(Offer:ducky_check_offer):void =
        if (Offer.Accepted?):
            Logger.Print("Deal at {Offer.Price} gold")

    OnSaid(Speaker:?agent, Said:message):void =
        Logger.Print("NPC finished a line")

    OnStopped(Interrupted:logic):void =
        if (Interrupted?) then Logger.Print("NPC was interrupted")

    OnFailed(Error:ai_error):void =
        if (ai_moderated_error[Error]) then Logger.Print("Moderated reply replaced")
        else Logger.Print("Prompt failed")

    OnEnd<override>():void =
        for (Cancel : Cancels):
            Cancel.Cancel()
        if (Entity := GetEntity[], Playspace := Entity.GetPlayspaceForEntity[]):
            for (Player : Playspace.GetPlayers()):
                Player.ClearConversationTarget()
