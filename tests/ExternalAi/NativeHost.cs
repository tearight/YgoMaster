using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Diagnostics;
using YgoMaster;
using YgoMaster.ExternalAi;
using YgoMasterClient.ExternalAi;

namespace YgoMaster
{
    [StructLayout(LayoutKind.Sequential)]
    struct PvpBasicVal
    {
        public short CardID, EffectID;
        public int Atk, Def, OrgAtk, OrgDef;
        public short Type, Attr, Element, Level;
        public byte Rank, VoidMagic, VoidTrap, VoidMonst;
    }
}
namespace YgoMasterClient
{
    static class ClientSettings { public static string ExternalAiConfigPath; }
    // Export binding shim for a standalone host. The production decoder/controller/worker are compiled unchanged.
    class NativeExport<T> { public T Original; public NativeExport(T value) { Original = value; } }
    unsafe static partial class DuelDll
    {
        public static int MyID = 0;
        public static int RivalID { get { return 1 - MyID; } }
        public static bool IsPvpDuel, IsPvpSpectator;
        public static List<Action> ActionsToRunInNextSysAct = new List<Action>();
        delegate int Get0();
        delegate void Void0();
        delegate uint UInt0();
        delegate int Get1(int a);
        delegate int Get2(int a, int b);
        delegate int Get3(int a, int b, int c);
        delegate uint UInt3(int a, int b, int c);
        [return: MarshalAs(UnmanagedType.I1)] delegate bool Bool2(int a, int b);
        delegate void Set1(int a);
        delegate void Set2(int a, int b);
        delegate void SetUInt(uint a);
        delegate void Command(int a, int b, int c, int d);
        delegate void Basic(int a, int b, int c, ref PvpBasicVal value);
        delegate int Work(IntPtr value);
        delegate void Pointers(IntPtr a, IntPtr b);
        delegate void Data(IntPtr a);
        delegate void DataSize(IntPtr a, int size);
        delegate void SetDeck(int p, int[] main, int mainCount, int[] extra, int extraCount, int[] side, int sideCount);
        delegate int Init(int type, bool tag, int life0, int life1, int hand0, int hand1, bool noShuffle);
        delegate int Run(int id, int a, int b, int c);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr LoadLibrary(string path);
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr module, string name);
        static IntPtr module;
        static NativeExport<Set2> hookDLL_DuelSetPlayerType, hookDLL_DuelListSetCardExData;
        static NativeExport<Command> hookDLL_DuelComDoCommand;
        static NativeExport<Set1> hookDLL_DuelComMovePhase, hookDLL_DuelListSetIndex;
        static NativeExport<Get0> hookDLL_DuelComCancelCommand, hookDLL_DuelListGetItemMax, hookDLL_DuelListGetSelectMin, hookDLL_DuelListGetSelectMax, hookDLL_DuelListIsMultiMode;
        static NativeExport<SetUInt> hookDLL_DuelDlgSetResult;
        static NativeExport<Get1> hookDLL_DuelListGetItemID, hookDLL_DuelListGetItemAttribute, hookDLL_DuelListGetItemUniqueID, hookDLL_DuelGetLP;
        static NativeExport<Get2> hookDLL_DuelGetCardNum;
        static NativeExport<Get3> hookDLL_DuelGetCardUniqueID;
        static NativeExport<Get3> hookDLL_DuelGetCardFace;
        static NativeExport<Get0> hookDLL_DuelWhichTurnNow;
        static NativeExport<UInt3> hookDLL_DuelComGetCommandMask;
        static NativeExport<UInt0> hookDLL_DuelComGetMovablePhase, hookDLL_DuelGetTurnNum, hookDLL_DuelGetCurrentPhase;
        static NativeExport<Bool2> hookDLL_DuelGetHandCardOpen;
        static NativeExport<Basic> hookDLL_DuelGetCardBasicVal;
        static T Bind<T>(string name) where T : class
        {
            IntPtr pointer = GetProcAddress(module, name);
            if (pointer == IntPtr.Zero) throw new Exception("missing export " + name);
            return Marshal.GetDelegateForFunctionPointer(pointer, typeof(T)) as T;
        }
        static NativeExport<T> Export<T>(string name) where T : class { return new NativeExport<T>(Bind<T>(name)); }
        static List<GCHandle> buffers = new List<GCHandle>();
        static IntPtr Bytes(string path)
        {
            GCHandle pin = GCHandle.Alloc(File.ReadAllBytes(path), GCHandleType.Pinned); buffers.Add(pin); return pin.AddrOfPinnedObject();
        }
        static List<object> requests = new List<object>();
        static bool uiWaitsForInput;
        static int submittedUiBusyCalls;
        static int submittedUiBusyOverrides;
        static Run view = (id, a, b, c) => { originalViewCalls++; return 0; };
        static HashSet<string> seen = new HashSet<string>(), consumed = new HashSet<string>();
        static void Observe(InputSession previous)
        {
            if (previous != null && previous.FinishState == "applied") consumed.Add(Protocol.Text(previous.Request, "decisionId"));
            if (externalAiInput != null && seen.Add(Protocol.Text(externalAiInput.Request, "decisionId")))
            {
                requests.Add(externalAiInput.Request);
                for (int player = 0; player < 2; player++) for (int pos = 0; pos <= 12; pos++)
                    if (hookDLL_DuelGetCardNum.Original(player, pos) > 0)
                        Console.WriteLine("FACE " + player + " " + pos + " " + hookDLL_DuelGetCardFace.Original(player, pos, 0));
                Console.WriteLine("REQUEST " + Protocol.Serialize(externalAiInput.Request));
                if (externalAiInput.EffectId == 4 && externalAiProfile.Read32(0x3cd0) == 8)
                {
                    int actor = externalAiProfile.Actor(4), count = hookDLL_DuelGetCardNum.Original(actor, 13);
                    Console.WriteLine("HAND_SELECTION_STATE " + Protocol.Serialize(new Dictionary<string, object> {
                        {"kind", externalAiProfile.Read32(0x3cec)}, {"remaining", externalAiProfile.Read16(0x3dbc)},
                        {"masks", Enumerable.Range(0, count).Select(i => hookDLL_DuelComGetCommandMask.Original(actor, 13, i)).ToArray()}
                    }));
                }
                if (externalAiInput.EffectId == 56 || externalAiInput.EffectId == 55)
                {
                    int mixCount = externalAiProfile.Read32(0x3ca0);
                    int itemCount = hookDLL_DuelListGetItemMax.Original();
                    List<object> items = new List<object>();
                    if (externalAiInput.EffectId == 56 && itemCount >= 0 && itemCount <= 300)
                        for (int i = 0; i < itemCount; i++) items.Add(new Dictionary<string, object> {
                            {"id", hookDLL_DuelListGetItemID.Original(i)}, {"uid", hookDLL_DuelListGetItemUniqueID.Original(i)},
                            {"attribute", hookDLL_DuelListGetItemAttribute.Original(i)},
                            {"from", Bind<Get1>("DLL_DuelListGetItemFrom")(i)}, {"message", Bind<Get1>("DLL_DuelListGetItemMsg")(i)}
                        });
                    Console.WriteLine("INPUT_STATE " + Protocol.Serialize(new Dictionary<string, object> {
                        {"listType", externalAiProfile.ListType}, {"mixCount", mixCount},
                        {"mixParts", Enumerable.Range(0, Math.Max(0, Math.Min(4, mixCount))).Select(i => (uint)externalAiProfile.Read32(0x3ca4 + i * 4)).ToArray()},
                        {"defaultResult", externalAiProfile.Read32(0x3c9c)}, {"items", items}
                    }));
                }
            }
        }
        static Run callback = (id, a, b, c) =>
        {
            InputSession previous = externalAiInput;
            Console.WriteLine("EVENT " + id + " " + a + " " + b + " " + c);
            ExternalAiOnRunEffect(id, a, b, c);
            Observe(previous);
            return originalViewCallback(id, a, b, c);
        };
        static Get1 busy = id => {
            if (ExternalAiControlsBusy(id))
            {
                if (uiWaitsForInput && externalAiInput.Submitted) submittedUiBusyOverrides++;
                return ExternalAiBusy(id);
            }
            return originalViewBusy(id);
        };
        static int ViewBusy(int id)
        {
            // A view can still await its button action after the app submits a result.
            if (uiWaitsForInput && ExternalAiOwnsInput && externalAiInput.Submitted &&
                (externalAiInput.EffectId == id || (externalAiInput.EffectId == 56 && id == 55)))
            { submittedUiBusyCalls++; return 1; }
            return 0;
        }
        static void BindExports()
        {
            hookDLL_DuelSetPlayerType = Export<Set2>("DLL_DuelSetPlayerType");
            hookDLL_DuelListSetCardExData = Export<Set2>("DLL_DuelListSetCardExData");
            hookDLL_DuelComDoCommand = Export<Command>("DLL_DuelComDoCommand");
            hookDLL_DuelComMovePhase = Export<Set1>("DLL_DuelComMovePhase");
            hookDLL_DuelListSetIndex = Export<Set1>("DLL_DuelListSetIndex");
            hookDLL_DuelComCancelCommand = Export<Get0>("DLL_DuelComCancelCommand");
            hookDLL_DuelDlgSetResult = Export<SetUInt>("DLL_DuelDlgSetResult");
            hookDLL_DuelListGetItemMax = Export<Get0>("DLL_DuelListGetItemMax");
            hookDLL_DuelListGetSelectMin = Export<Get0>("DLL_DuelListGetSelectMin");
            hookDLL_DuelListGetSelectMax = Export<Get0>("DLL_DuelListGetSelectMax");
            hookDLL_DuelListIsMultiMode = Export<Get0>("DLL_DuelListIsMultiMode");
            hookDLL_DuelListGetItemID = Export<Get1>("DLL_DuelListGetItemID");
            hookDLL_DuelListGetItemAttribute = Export<Get1>("DLL_DuelListGetItemAttribute");
            hookDLL_DuelListGetItemUniqueID = Export<Get1>("DLL_DuelListGetItemUniqueID");
            hookDLL_DuelGetLP = Export<Get1>("DLL_DuelGetLP");
            hookDLL_DuelGetCardNum = Export<Get2>("DLL_DuelGetCardNum");
            hookDLL_DuelGetCardUniqueID = Export<Get3>("DLL_DuelGetCardUniqueID");
            hookDLL_DuelGetCardFace = Export<Get3>("DLL_DuelGetCardFace");
            hookDLL_DuelWhichTurnNow = Export<Get0>("DLL_DuelWhichTurnNow");
            hookDLL_DuelComGetCommandMask = Export<UInt3>("DLL_DuelComGetCommandMask");
            hookDLL_DuelComGetMovablePhase = Export<UInt0>("DLL_DuelComGetMovablePhase");
            hookDLL_DuelGetTurnNum = Export<UInt0>("DLL_DuelGetTurnNum");
            hookDLL_DuelGetCurrentPhase = Export<UInt0>("DLL_DuelGetCurrentPhase");
            hookDLL_DuelGetHandCardOpen = Export<Bool2>("DLL_DuelGetHandCardOpen");
            hookDLL_DuelGetCardBasicVal = Export<Basic>("DLL_DuelGetCardBasicVal");
        }
        static int Main(string[] args)
        {
            string dllPath = args[0], data = args[1]; ClientSettings.ExternalAiConfigPath = args[2];
            int decisionCount = int.Parse(args[3]), timeoutSeconds = int.Parse(args[4]);
            uiWaitsForInput = args.Length > 6 && args[6] == "ui-waits-for-input";
            originalViewCallback = view; originalViewBusy = ViewBusy;
            module = LoadLibrary(dllPath); if (module == IntPtr.Zero) throw new Exception("DLL load failed");
            BindExports(); ExternalAiInit(module, dllPath);
            if (externalAiWorker == null) throw new Exception("bridge/profile not initialized");
            if (args.Length > 7 && !string.IsNullOrEmpty(args[7])) InstallNativeHooks(args[7]);
            string[] paths = {"#/CARD_IntID.bytes", "#/CARD_Prop.bytes", "MD/CARD_Same.bytes", "#/CARD_Genre.bytes", "#/CARD_Named.bytes", "MD/CARD_Link.bytes"};
            string[] setters = {"DLL_SetInternalID", "DLL_SetCardProperty", "DLL_SetCardSame", "DLL_SetCardGenre", "DLL_SetCardNamed", "DLL_SetCardLink"};
            for (int i = 0; i < paths.Length; i++)
            {
                string path = Path.Combine(data, paths[i]);
                IntPtr pointer = Bytes(path);
                if (i == 1 || i == 2 || i == 5) Bind<DataSize>(setters[i])(pointer, checked((int)new FileInfo(path).Length));
                else Bind<Data>(setters[i])(pointer);
            }
            Work setWork = Bind<Work>("DLL_SetWorkMemory");
            int size = setWork(IntPtr.Zero); if (size != EngineProfile.WorkSize) throw new Exception("work size mismatch");
            IntPtr work = Marshal.AllocHGlobal(size); setWork(work);
            if (nativeHooks.Count == 0) externalAiProfile.SetWork(work);
            Bind<Pointers>("DLL_SetEffectDelegate")(
                Marshal.GetFunctionPointerForDelegate(nativeHooks.Count > 0 ? view : callback),
                Marshal.GetFunctionPointerForDelegate(nativeHooks.Count > 0 ? originalViewBusy : busy));
            Bind<Void0>("DLL_DuelSysClearWork")();
            ExternalAiBegin(GameMode.SoloSingle);
            Bind<Set1>("DLL_DuelSetMyPlayerNum")(0);
            Bind<SetUInt>("DLL_DuelSetRandomSeed")(1234);
            SetDeck deck = Bind<SetDeck>("DLL_DuelSysSetDeck2");
            string scenario = args[5];
            int cardId = scenario == "spell-target" ? 4909 : scenario == "discard-two" ? 4812 : scenario == "twin-target" ? 12175 : scenario == "chain-cost" ? 4862 : 4084;
            int[] main = Enumerable.Repeat(cardId, 40).ToArray();
            int[] opponentMain = scenario == "chain-cost" ? Enumerable.Repeat(4812, 40).ToArray() : main;
            deck(0, opponentMain, opponentMain.Length, new int[0], 0, new int[0], 0); deck(1, main, main.Length, new int[0], 0, new int[0], 0);
            if (nativeHooks.Count > 0)
            {
                Bind<Set2>("DLL_DuelSetPlayerType")(0, 1);
                Bind<Set2>("DLL_DuelSetPlayerType")(1, 1);
            }
            else
            {
                hookDLL_DuelSetPlayerType.Original(0, 1);
                hookDLL_DuelSetPlayerType.Original(1, ExternalAiPlayerType(1, 1));
            }
            Bind<Set1>("DLL_DuelSetFirstPlayer")(1);
            Bind<SetUInt>("DLL_DuelSetDuelLimitedType")(0);
            Bind<Init>("DLL_DuelSysInitCustom")(0, false, 8000, 8000, 5, 5, false);
            Console.WriteLine("INITIALIZED normal duel with game content");
            Get0 tick = Bind<Get0>("DLL_DuelSysAct"); Stopwatch watch = Stopwatch.StartNew();
            while (watch.Elapsed < TimeSpan.FromSeconds(timeoutSeconds) && consumed.Count < decisionCount)
            {
                if (!externalAiEnabled) break;
                AttemptCompetingUiInput();
                int result = nativeHooks.Count > 0 ? tick() : ControlledTick(tick);
                if (result != 0) break;
                Thread.Sleep(5);
            }
            List<object> finalCards = new List<object>();
            for (int player = 0; player < 2; player++) for (int pos = 0; pos < 18; pos++) if (pos != 15)
                for (int index = 0; index < hookDLL_DuelGetCardNum.Original(player, pos); index++)
                    finalCards.Add(ExternalAiCard(player, pos, index, RivalID));
            Console.WriteLine("SUMMARY " + Protocol.Serialize(new Dictionary<string, object> {
                {"normalInitialization", true}, {"profileSha256", EngineProfile.Sha256}, {"requests", requests},
                {"consumedIds", consumed.ToArray()}, {"targetPlayerType", externalAiProfile.Read32(0x2c5cbc + 12)},
                {"elapsedSeconds", watch.Elapsed.TotalSeconds}, {"gameProcessInjected", false}, {"finalCards", finalCards},
                {"uiWaitsForInput", uiWaitsForInput}, {"submittedUiBusyCalls", submittedUiBusyCalls}, {"submittedUiBusyOverrides", submittedUiBusyOverrides},
                {"nativeHookCount", nativeHooks.Count}, {"nativeSysActCalls", nativeSysActCalls},
                {"suppressedUiInputs", suppressedUiInputs}, {"originalViewCalls", originalViewCalls}, {"cpuEvaluatorCalls", cpuEvaluatorCalls}
            }));
            Thread.Sleep(1500);
            externalAiWorker.Dispose();
            return consumed.Count >= decisionCount ? 0 : 3;
        }
    }
}
