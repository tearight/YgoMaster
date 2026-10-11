using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using YgoMaster.ExternalAi;
using YgoMasterClient.ExternalAi;

// Only the unused IL2CPP overload's type is stubbed. Hook<T> and its loader API
// are compiled from production Hook.cs; no game metadata is loaded in this host.
namespace IL2CPP { class IL2Method { public IntPtr ptr; } }

namespace YgoMasterClient
{
    unsafe static partial class DuelDll
    {
        static readonly List<object> nativeHooks = new List<object>();
        static NativeExport<Get0> nativeSysAct;
        static NativeExport<Work> nativeSetWork;
        static NativeExport<Pointers> nativeSetDelegate;
        static Run originalViewCallback;
        static Get1 originalViewBusy;
        static int nativeSysActCalls, suppressedUiInputs, originalViewCalls;
        delegate int TimingEvaluator(int player, IntPtr context);
        static NativeExport<Get0> cpuMain, cpuOther, cpuDialog;
        static NativeExport<Get1> cpuBattle;
        static NativeExport<TimingEvaluator> cpuTiming;
        static readonly Dictionary<string, int[]> cpuEvaluatorCalls = new Dictionary<string, int[]> {
            {"main", new int[3]}, {"battle", new int[3]}, {"timing", new int[3]}, {"other", new int[3]}, {"dialog", new int[3]}
        };
        static readonly HashSet<string> uiAttempted = new HashSet<string>();

        static NativeExport<T> Intercept<T>(string name, T detour) where T : class
        {
            return InterceptAddress(name, GetProcAddress(module, name), detour);
        }
        static NativeExport<T> InterceptAddress<T>(string name, IntPtr address, T detour) where T : class
        {
            Hook<T> hook = new Hook<T>(detour, address);
            nativeHooks.Add(hook);
            int result = PInvoke.WL_EnableHook(address);
            if (result != 0) throw new Exception("native hook enable failed: " + name + " " + result);
            return new NativeExport<T>(hook.Original);
        }

        static void CountCpu(string name, int actor) { cpuEvaluatorCalls[name][actor == 0 || actor == 1 ? actor : 2]++; }

        static void InstallNativeHooks(string loader)
        {
            if (LoadLibrary(loader) == IntPtr.Zero) throw new Exception("loader load failed");
            nativeSetWork = Intercept<Work>("DLL_SetWorkMemory", pointer => {
                int result = nativeSetWork.Original(pointer);
                if (pointer != IntPtr.Zero) externalAiProfile.SetWork(pointer);
                return result;
            });
            nativeSetDelegate = Intercept<Pointers>("DLL_SetEffectDelegate", (run, isBusy) => {
                originalViewCallback = (Run)Marshal.GetDelegateForFunctionPointer(run, typeof(Run));
                originalViewBusy = (Get1)Marshal.GetDelegateForFunctionPointer(isBusy, typeof(Get1));
                nativeSetDelegate.Original(Marshal.GetFunctionPointerForDelegate(callback), Marshal.GetFunctionPointerForDelegate(busy));
            });
            hookDLL_DuelSetPlayerType = Intercept<Set2>("DLL_DuelSetPlayerType", (player, type) =>
                hookDLL_DuelSetPlayerType.Original(player, ExternalAiPlayerType(player, type)));
            hookDLL_DuelDlgSetResult = Intercept<SetUInt>("DLL_DuelDlgSetResult", result => {
                if (ExternalAiOwnsInput) { suppressedUiInputs++; return; }
                hookDLL_DuelDlgSetResult.Original(result);
            });
            hookDLL_DuelComDoCommand = Intercept<Command>("DLL_DuelComDoCommand", (player, pos, index, command) => {
                if (ExternalAiOwnsInput) { suppressedUiInputs++; return; }
                hookDLL_DuelComDoCommand.Original(player, pos, index, command);
            });
            nativeSysAct = Intercept<Get0>("DLL_DuelSysAct", () => {
                nativeSysActCalls++;
                return ControlledTick(nativeSysAct.Original);
            });
            // These signatures and dispatch actors were measured in the pinned profile.
            // Counters forward to original bodies; they never replace a CPU decision.
            cpuMain = InterceptAddress<Get0>("cpu_main", IntPtr.Add(module, 0xc28d10), () => {
                CountCpu("main", externalAiProfile.Actor(4)); return cpuMain.Original();
            });
            cpuBattle = InterceptAddress<Get1>("cpu_battle", IntPtr.Add(module, 0xc2a6d0), player => {
                CountCpu("battle", player); return cpuBattle.Original(player);
            });
            cpuTiming = InterceptAddress<TimingEvaluator>("cpu_timing", IntPtr.Add(module, 0xc2a4f0), (player, context) => {
                CountCpu("timing", player); return cpuTiming.Original(player, context);
            });
            cpuOther = InterceptAddress<Get0>("cpu_other", IntPtr.Add(module, 0xc2e150), () => {
                CountCpu("other", externalAiProfile.Actor(4)); return cpuOther.Original();
            });
            cpuDialog = InterceptAddress<Get0>("cpu_dialog", IntPtr.Add(module, 0xc31bc0), () => {
                CountCpu("dialog", externalAiProfile.Actor(55)); return cpuDialog.Original();
            });
        }

        static int ControlledTick(Get0 tick)
        {
            ExternalAiBeforeSysAct();
            if (!externalAiEnabled) return 0;
            Action[] queued;
            lock (ActionsToRunInNextSysAct) { queued = ActionsToRunInNextSysAct.ToArray(); ActionsToRunInNextSysAct.Clear(); }
            foreach (Action action in queued) action();
            InputSession previous = externalAiInput;
            int result = tick(); ExternalAiAfterSysAct(result); Observe(previous);
            return result;
        }

        static void AttemptCompetingUiInput()
        {
            if (nativeHooks.Count == 0 || !ExternalAiOwnsInput || !externalAiInput.Hold ||
                !uiAttempted.Add(Protocol.Text(externalAiInput.Request, "decisionId"))) return;
            // Call the actual hooked export with a conflicting value. Its original work
            // result must remain unchanged while the external session owns this input.
            int before = externalAiProfile.Read32(0x3c9c);
            Bind<SetUInt>("DLL_DuelDlgSetResult")(999);
            if (before != externalAiProfile.Read32(0x3c9c)) throw new Exception("competing UI input changed native result");
        }
    }
}
