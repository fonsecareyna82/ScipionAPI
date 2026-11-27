import json

import pytest

from app.backend.api.services.assistant_actions import (
    ProposalError, applyChecks, nextStepCard, parameterChanges, relaunchCard, relaunchModes, stopCard,
)
from app.backend.api.services.assistant_agent import AssistantAgent, AssistantTools, changesOf

HELP = {"className": "Prot2D", "label": "2D classification", "params": [
    {"name": "numberOfClasses", "label": "Number of classes", "pointer": False},
    {"name": "resolution", "label": "Max resolution", "pointer": False},
    {"name": "correctCtf", "label": "Correct CTF", "pointer": False},
    {"name": "inputParticles", "label": "Input particles", "pointer": True},
]}
PARAMS = {"numberOfClasses": 50, "resolution": 8.0, "correctCtf": True, "inputParticles": "1009708",
          "_queueParams": "[]", "hostName": "localhost"}


def protocol(status="finished"):
    return {"protocolId": "37", "label": "alignPCA-2D", "className": "Prot2D", "status": status, "params": PARAMS}


# Parameters ----------------------------------------------------------------------------------------------------

def test_ChangesTakeTheTypeOfTheCurrentValue():
    changes = parameterChanges(PARAMS, HELP, {"numberOfClasses": "100", "resolution": "6", "correctCtf": "no"})
    assert changes == [
        {"name": "numberOfClasses", "label": "Number of classes", "from": 50, "to": 100},
        {"name": "resolution", "label": "Max resolution", "from": 8.0, "to": 6.0},
        {"name": "correctCtf", "label": "Correct CTF", "from": True, "to": False},
    ]


def test_SameValueIsNoChange():
    assert parameterChanges(PARAMS, HELP, {"numberOfClasses": "50"}) == []


@pytest.mark.parametrize("changes, said", [
    ({"inputParticles": "5"}, "input"),
    ({"hostName": "other"}, "no parameter called hostName"),
    ({"_queueParams": "x"}, "no parameter called _queueParams"),
    ({"numberOfClasses": "many"}, "whole number"),
    ({"numberOfClasses": "2.5"}, "whole number"),
    ({"correctCtf": "maybe"}, "yes or no"),
])
def test_OnlyVisibleNonInputParamsWithRightValues(changes, said):
    with pytest.raises(ProposalError) as error:
        parameterChanges(PARAMS, HELP, changes)
    assert said in str(error.value)


# Restart or continue ---------------------------------------------------------------------------------------------

def test_ChangedParametersAlwaysRestart():
    assert relaunchModes("failed", True) == ("restart", ["restart"])


def test_FailedWithoutChangesContinuesAndOffersRestart():
    assert relaunchModes("failed", False) == ("continue", ["continue", "restart"])
    assert relaunchModes("aborted", False) == ("continue", ["continue", "restart"])


def test_FinishedOrNeverRunRestarts():
    assert relaunchModes("finished", False) == ("restart", ["restart"])
    assert relaunchModes("saved", False) == ("restart", ["restart"])


def test_RunningMustBeStoppedFirst():
    with pytest.raises(ProposalError) as error:
        relaunchModes("running", False)
    assert "stopped first" in str(error.value)


# Cards -----------------------------------------------------------------------------------------------------------

def test_RelaunchCardListsTheChildrenButNotTheProtocol():
    preflight = {"affectedProtocols": [
        {"protocolId": "37", "runName": "alignPCA-2D", "status": "finished", "active": False},
        {"protocolId": "105", "runName": "subset", "status": "finished", "active": False},
        {"protocolId": "106", "runName": "initial model", "status": "running", "active": True},
    ]}
    card = relaunchCard(7, protocol(), HELP, {"numberOfClasses": 100}, preflight, "Fewer classes")
    assert card["action"] == "relaunch" and card["mode"] == "restart" and card["modes"] == ["restart"]
    assert [child["protocolId"] for child in card["children"]] == ["105", "106"]
    assert card["children"][1]["active"] is True
    assert card["changes"][0]["to"] == 100
    assert card["reason"] == "Fewer classes"


def test_RelaunchWithNothingToChangeIsRefused():
    with pytest.raises(ProposalError):
        relaunchCard(7, protocol(), HELP, {"numberOfClasses": 50}, {}, "")



def test_ARelaunchNeverRenames():
    # A new name must not launch the protocol: that is a rename's work
    with pytest.raises(ProposalError) as error:
        relaunchCard(7, protocol(), HELP, {"runName": "CS - 3D H"}, {}, "")
    assert "propose_rename" in str(error.value)


def test_StopOnlyWhatRuns():
    assert stopCard(7, protocol("running"))["action"] == "stop"
    with pytest.raises(ProposalError):
        stopCard(7, protocol("finished"))


def test_NextStepNeedsAnInstalledProtocol():
    card = nextStepCard(7, protocol(), HELP)
    assert card["nextClassName"] == "Prot2D" and card["protocolId"] == "37"
    with pytest.raises(ProposalError):
        nextStepCard(7, protocol(), None)


# Applying ------------------------------------------------------------------------------------------------------

def test_ApplyChecksAgainAndGivesOnlyTheChangedParams():
    plan = applyChecks(protocol(), HELP, "relaunch", "restart", "all", {"numberOfClasses": "100"}, True)
    assert plan == {"params": {"numberOfClasses": 100}, "mode": "restart", "scope": "all"}


def test_ApplyNeedsTheScopeWhenThereAreChildren():
    with pytest.raises(ProposalError) as error:
        applyChecks(protocol(), HELP, "relaunch", "restart", None, {}, True)
    assert "whole workflow" in str(error.value)
    assert applyChecks(protocol(), HELP, "relaunch", "restart", None, {}, False)["scope"] == "single"


def test_ApplyRefusesWhatChangedMeanwhile():
    with pytest.raises(ProposalError):
        applyChecks(protocol("running"), HELP, "relaunch", "restart", "single", {}, False)
    with pytest.raises(ProposalError):
        applyChecks(protocol("finished"), HELP, "relaunch", "continue", "single", {}, False)
    with pytest.raises(ProposalError):
        applyChecks(protocol("finished"), HELP, "stop", "", None, {}, False)
    with pytest.raises(ProposalError):
        applyChecks(None, HELP, "relaunch", "restart", "single", {}, False)


# The agent with proposals ----------------------------------------------------------------------------------------

class ScriptedModel:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def chat(self, messages, tools=None):
        self.sent.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        return {"message": self.replies.pop(0), "usage": {"inputTokens": 1, "outputTokens": 1}}


def tools(propose=True):
    read = [lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]
    if not propose:
        return AssistantTools(*read)
    relaunch = lambda p, q, changes, reason: relaunchCard(p, protocol(), HELP, changes, {}, reason)
    stop = lambda p, q, reason: stopCard(p, protocol(), reason)
    nextStep = lambda p, q, className, reason: nextStepCard(p, protocol(), HELP, reason)
    return AssistantTools(*read, relaunch, stop, nextStep)


def call(name, args):
    return {"content": None, "tool_calls": [{"id": "c1", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_ProposalToolsOnlyWhenAllowed():
    model = ScriptedModel([{"content": "ok"}])
    AssistantAgent(model, tools(propose=False)).answer("hi", "")
    names = {tool["function"]["name"] for tool in model.sent[0]["tools"]}
    assert not any(name.startswith("propose_") for name in names)
    assert "You can only read" in model.sent[0]["messages"][0]["content"]

    model = ScriptedModel([{"content": "ok"}])
    AssistantAgent(model, tools()).answer("hi", "")
    names = {tool["function"]["name"] for tool in model.sent[0]["tools"]}
    assert {"propose_relaunch", "propose_stop", "propose_next_step"} <= names
    assert "Never say that something was done" in model.sent[0]["messages"][0]["content"]


def test_ProposalBecomesACardAndTheModelIsToldNothingHappened():
    model = ScriptedModel([
        call("propose_relaunch", {"projectId": 7, "protocolId": "37", "reason": "Fewer classes",
                                  "changes": [{"name": "numberOfClasses", "value": "100"}]}),
        {"content": "I proposed relaunching it with 100 classes."}])
    answer = AssistantAgent(model, tools()).answer("relaunch with 100 classes", "")
    card = [card for card in answer["cards"] if card["kind"] == "action"][0]
    assert card["changes"][0]["to"] == 100
    told = json.loads(model.sent[1]["messages"][-1]["content"])
    assert told["proposed"] is True and "Nothing happened yet" in told["note"]


def test_RefusedProposalIsExplainedToTheModel():
    model = ScriptedModel([call("propose_stop", {"projectId": 7, "protocolId": "37", "reason": "x"}),
                           {"content": "It is not running."}])
    answer = AssistantAgent(model, tools()).answer("stop it", "")
    assert "nothing to stop" in model.sent[1]["messages"][-1]["content"]
    assert not [card for card in answer["cards"] if card["kind"] == "action"]


def test_ChangesListOrObject():
    assert changesOf([{"name": "a", "value": "1"}]) == {"a": "1"}
    assert changesOf({"a": 1}) == {"a": 1}
    assert changesOf(None) == {}
    with pytest.raises(ValueError):
        changesOf([{"value": "1"}])


# Duplicate and delete ------------------------------------------------------------------------------------------

from app.backend.api.services.assistant_actions import blockingChildren, deleteCard, duplicateCard  # noqa: E402


def test_DuplicateCarriesTheChangesAndAnyStatus():
    card = duplicateCard(7, protocol("running"), HELP, {"numberOfClasses": "30"})
    assert card["action"] == "duplicate" and card["changes"][0]["to"] == 30
    assert duplicateCard(7, protocol(), HELP, {})["changes"] == []
    assert applyChecks(protocol(), HELP, "duplicate", "", None, {"numberOfClasses": "30"}, False) == {
        "params": {"numberOfClasses": 30}}


def test_DeleteListsWhatIsLost():
    outputs = [{"outputName": "outputClasses", "setClassName": "SetOfClasses2D", "size": 42}]
    children = [{"protocolId": "105", "label": "subset", "status": "new", "active": False, "hasOutputs": False}]
    card = deleteCard(7, protocol(), outputs, children, "Not needed")
    assert card["outputs"] == [{"name": "outputClasses", "type": "SetOfClasses2D", "size": 42}]
    assert card["children"] == [{"protocolId": "105", "label": "subset", "status": "new"}]


def test_DeleteRefusedWhileItOrItsChildrenRunOrHaveResults():
    with pytest.raises(ProposalError):
        deleteCard(7, protocol("running"), [], [])
    busy = [{"protocolId": "105", "active": False, "hasOutputs": True},
            {"protocolId": "106", "active": True, "hasOutputs": False},
            {"protocolId": "107", "active": False, "hasOutputs": False}]
    assert [child["protocolId"] for child in blockingChildren(busy)] == ["105", "106"]
    with pytest.raises(ProposalError) as error:
        deleteCard(7, protocol(), [], busy)
    assert "#105, #106" in str(error.value)


def test_DeleteNeedsTheNumberWritten():
    with pytest.raises(ProposalError) as error:
        applyChecks(protocol(), HELP, "delete", "", None, {}, False, confirm="", children=[])
    assert "(37)" in str(error.value)
    with pytest.raises(ProposalError):
        applyChecks(protocol(), HELP, "delete", "", None, {}, False, confirm="38", children=[])
    assert applyChecks(protocol(), HELP, "delete", "", None, {}, False, confirm="#37", children=[]) == {}


def test_DeleteToolOnlyWhenTurnedOn():
    read = [lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]
    proposals = [lambda *a: {}, lambda *a: {}, lambda *a: {}, lambda *a: {}]
    for canDelete in (False, True):
        tools_ = AssistantTools(*read, *proposals, (lambda *a: {}) if canDelete else None)
        model = ScriptedModel([{"content": "ok"}])
        AssistantAgent(model, tools_).answer("hi", "")
        names = {tool["function"]["name"] for tool in model.sent[0]["tools"]}
        assert "propose_duplicate" in names
        assert ("propose_delete" in names) is canDelete
        system = model.sent[0]["messages"][0]["content"]
        assert ("only when the user asks to delete in their own words" in system) is canDelete
        assert ("You cannot delete protocols or projects" in system) is not canDelete


from app.backend.api.services import assistant_actions as actions  # noqa: E402


def _items(*statuses, outputs=None):
    return [{"protocolId": str(10 + index), "label": "p%d" % index, "status": status,
             "active": status == "running", "outputs": (outputs or {}).get(index, [])}
            for index, status in enumerate(statuses)]


def test_SubworkflowCardsListEveryProtocol():
    copy = actions.subworkflowCard("copyworkflow", 7, _items("finished", "running"), "try", launch=True)
    assert copy["launch"] is True and [item["protocolId"] for item in copy["protocols"]] == ["10", "11"]
    assert "outputs" not in copy["protocols"][0]
    gone = actions.subworkflowCard("deletefrom", 7, _items("finished", "failed", outputs={
        0: [{"outputName": "outputCTF", "setClassName": "SetOfCTF", "size": 28}]}))
    assert gone["protocols"][0]["outputs"] == [{"name": "outputCTF", "type": "SetOfCTF", "size": 28}]


@pytest.mark.parametrize("action", ["reset", "deletefrom"])
def test_NothingMayRunToResetOrDelete(action):
    with pytest.raises(actions.ProposalError, match="#11"):
        actions.subworkflowCard(action, 7, _items("finished", "running"))


def test_ResetNeedsSomethingThatRan():
    with pytest.raises(actions.ProposalError, match="nothing to reset"):
        actions.subworkflowCard("reset", 7, _items("saved", "new"))
    assert actions.subworkflowCard("reset", 7, _items("finished", "saved"))["action"] == "reset"


def test_TooBigASubworkflowIsRefused():
    with pytest.raises(actions.ProposalError, match="at most"):
        actions.subworkflowCard("copyworkflow", 7, _items(*["finished"] * (actions.MAX_SUBWORKFLOW + 1)))


def test_DeleteFromIsConfirmedWithHowManyAndTheSameList():
    items = _items("finished", "finished")
    actions.deleteFromChecks(items, ["11", "10"], " 2 ")
    with pytest.raises(actions.ProposalError, match="Write how many"):
        actions.deleteFromChecks(items, ["10", "11"], "10")
    with pytest.raises(actions.ProposalError, match="changed"):
        actions.deleteFromChecks(items, ["10"], "2")


def test_TagCard():
    protocols = [{"protocolId": "5", "label": "ctf"}, {"protocolId": "6", "label": "picking"}]
    card = actions.tagCard(7, protocols, " to   check ", None, {}, "asked")
    assert card["tag"] == "to check" and card["newTag"] is True
    existing = {"id": "t1", "title": "Good", "color": "#0a0"}
    card = actions.tagCard(7, protocols, "good", existing, {"5": ["t1"]})
    assert card["tag"] == "Good" and card["newTag"] is False
    assert [item["already"] for item in card["protocols"]] == [True, False]
    with pytest.raises(actions.ProposalError, match="already have"):
        actions.tagCard(7, protocols[:1], "good", existing, {"5": ["t1"]})
    with pytest.raises(actions.ProposalError):
        actions.tagCard(7, protocols, "x" * 61, None, {})


def test_TheModelGetsTheNewToolsOnlyWhenAllowed():
    from app.backend.api.services.assistant_agent import AssistantTools

    read = [lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]
    seen = []
    propose = dict(proposeRelaunch=lambda *a: {}, proposeStop=lambda *a: {}, proposeNextStep=lambda *a: {},
                   proposeSubworkflow=lambda *a: seen.append(a) or {"action": a[0]},
                   proposeTag=lambda *a: seen.append(a) or {"action": "tag"},
                   proposeRename=lambda *a: seen.append(a) or {"action": "rename"},
                   proposeSchedule=lambda *a: seen.append(a) or {"action": "schedule"},
                   proposeMany=lambda *a: seen.append(a) or {"action": a[1]},
                   proposeNewProject=lambda args: {"action": "newproject"},
                   proposeWatch=lambda *a: {"action": "watch"})
    names = lambda tools: {tool["function"]["name"] for tool in tools.definitions()}  # noqa: E731
    tools = AssistantTools(*read, **propose)
    assert {"propose_copy_subworkflow", "propose_reset", "propose_tag"} <= names(tools)
    assert "propose_delete_subworkflow" not in names(tools)
    tools.call("propose_copy_subworkflow", '{"projectId": 7, "protocolId": "5", "launch": "true", "reason": "r"}')
    tools.call("propose_tag", '{"projectId": 7, "protocolIds": ["5", 6], "tag": "x", "reason": "r"}')
    tools.call("propose_many", '{"projectId": 7, "what": "stop", "protocolIds": ["5", 6], "reason": "r"}')
    assert seen == [("copyworkflow", 7, "5", "r", True), (7, ["5", "6"], "x", "r"),
                    (7, "stopmany", ["5", "6"], "r")]
    withDelete = AssistantTools(*read, proposeDelete=lambda *a: {}, **propose)
    assert "propose_delete_subworkflow" in names(withDelete)
    assert "propose_tag" not in names(AssistantTools(*read))


def test_UntagCard():
    protocols = [{"protocolId": "5", "label": "ctf"}, {"protocolId": "6", "label": "picking"}]
    existing = {"id": "t1", "title": "Good", "color": "#0a0"}
    card = actions.tagCard(7, protocols, "good", existing, {"5": ["t1"]}, remove=True)
    assert card["action"] == "untag" and [item["already"] for item in card["protocols"]] == [True, False]
    with pytest.raises(actions.ProposalError, match="no tag called"):
        actions.tagCard(7, protocols, "other", None, {}, remove=True)
    with pytest.raises(actions.ProposalError, match="None of those"):
        actions.tagCard(7, protocols, "good", existing, {}, remove=True)



def test_RenameCardListsOnlyWhatChanges():
    protocol = {"protocolId": "5", "label": "ctffind", "className": "P", "status": "finished"}
    card = actions.renameCard(7, protocol, "old note", "  CTF   good ", None)
    assert card["changes"] == [{"field": "name", "from": "ctffind", "to": "CTF good"}]
    card = actions.renameCard(7, protocol, "old note", None, "thick ice", addToComment=True)
    assert card["changes"] == [{"field": "comment", "from": "old note", "to": "old note\nthick ice"}]
    with pytest.raises(actions.ProposalError, match="Nothing would change"):
        actions.renameCard(7, protocol, "old note", "ctffind", "old note")
    with pytest.raises(actions.ProposalError, match="empty"):
        actions.renameCard(7, protocol, "", "  ", None)
    assert actions.renamed(protocol, "old", card["changes"]) == ("ctffind", "old note\nthick ice")


def _row(protocolId, status, label="p"):
    return {"protocolId": protocolId, "label": label, "status": status, "className": "P"}


def test_ScheduleWaitsOnlyForWhatCanFinish():
    card = actions.scheduleCard(7, _row("40", "saved"), [_row("37", "running"), _row("38", "finished")], ["41"])
    assert [(item["protocolId"], item["done"]) for item in card["waitFor"]] == [("37", False), ("38", True)]
    with pytest.raises(actions.ProposalError, match="would wait forever"):
        actions.scheduleCard(7, _row("40", "saved"), [_row("41", "new")], ["41"])
    with pytest.raises(actions.ProposalError, match="relaunch it first"):
        actions.scheduleCard(7, _row("40", "saved"), [_row("37", "failed")], [])
    with pytest.raises(actions.ProposalError, match="already finished"):
        actions.scheduleCard(7, _row("40", "finished"), [_row("37", "running")], [])
    with pytest.raises(actions.ProposalError, match="running already"):
        actions.scheduleCard(7, _row("40", "running"), [_row("37", "running")], [])
    with pytest.raises(actions.ProposalError, match="itself"):
        actions.scheduleCard(7, _row("40", "new"), [_row("40", "new")], [])


def test_TheWaitListKeepsWhatItHad():
    assert actions.prerequisitesWith("12, 13", ["13", "37"]) == "12,13,37"
    assert actions.prerequisitesWith(None, ["37"]) == "37"


def test_UntagWithoutANameTakesTheOnlyTagTheyHave():
    tags = [{"id": "t1", "title": "CTF buena"}, {"id": "t2", "title": "hielo grueso"}]
    assert actions.tagToRemove({"137": ["t1"]}, tags) == "CTF buena"
    with pytest.raises(ProposalError) as error:
        actions.tagToRemove({"137": ["t1", "t2"]}, tags)
    assert "CTF buena, hielo grueso" in str(error.value)
    with pytest.raises(ProposalError):
        actions.tagToRemove({"137": []}, tags)


def _rows(**statuses):
    return [{"protocolId": key.lstrip("p"), "label": key, "status": value} for key, value in statuses.items()]


def test_StopManyLeavesOutWhatIsNotRunning():
    card = actions.manyCard(7, "stopmany", _rows(p30="running", p31="finished"), {}, "")
    assert [(item["protocolId"], item["skip"]) for item in card["items"]] == [("30", None), ("31", "not running")]
    with pytest.raises(ProposalError):
        actions.manyCard(7, "stopmany", _rows(p31="finished"), {}, "")


def test_RelaunchManyModesAndChoices():
    card = actions.manyCard(7, "relaunchmany", _rows(p30="aborted", p31="finished", p32="running"),
                            {"30": ["40"], "31": []}, "")
    assert [item.get("mode") for item in card["items"]] == ["continue", "restart", None]
    assert card["items"][2]["skip"].startswith("running")
    assert card["canContinue"] is True and card["needsScope"] is True


def test_RelaunchManyRefusesOneDependingOnAnother():
    with pytest.raises(ProposalError) as error:
        actions.manyCard(7, "relaunchmany", _rows(p30="failed", p40="failed"), {"30": ["40"], "40": []}, "")
    assert "whole workflow" in str(error.value)


def test_AtMostTwentyAtOnce():
    with pytest.raises(ProposalError):
        actions.manyCard(7, "stopmany", [{"protocolId": str(i), "status": "running"} for i in range(21)], {}, "")


def test_ShowInGraphLeavesOneFocusCard():
    from app.backend.api.services.assistant_agent import AssistantTools

    read = [lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]

    def show(projectId, protocolId):
        if protocolId == "99":
            raise ProposalError("There is no protocol 99 in that project")
        return {"projectId": projectId, "protocolId": protocolId, "label": "ctf"}

    tools = AssistantTools(*read, showProtocol=show)
    assert "show_in_graph" in {tool["function"]["name"] for tool in tools.definitions()}
    tools.call("show_in_graph", '{"projectId": 7, "protocolId": "30"}')
    tools.call("show_in_graph", '{"projectId": 7, "protocolId": "31"}')
    result, _ = tools.call("show_in_graph", '{"projectId": 7, "protocolId": "99"}')
    assert "no protocol 99" in result
    assert tools.cards == [{"kind": "focus", "projectId": 7, "protocolId": "31", "label": "ctf"}]
