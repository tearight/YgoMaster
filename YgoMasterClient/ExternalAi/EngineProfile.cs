using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace YgoMasterClient.ExternalAi
{
    // Offsets were measured against this DLL. Other revisions must provide a new profile.
    public sealed class EngineProfile
    {
        public const string Sha256 = "97bd4d136e39b0872e4a8a9171632f1f0bd9bb04d69af08e836c56e684d43c44";
        public const int WorkSize = 0x2c5ff4;
        readonly IntPtr module;
        IntPtr work;
        [UnmanagedFunctionPointer(CallingConvention.Winapi)]
        delegate int LocationPredicate(int player, int position, int index);
        public EngineProfile(IntPtr module, string path)
        {
            using (SHA256 sha = SHA256.Create())
            using (FileStream stream = File.OpenRead(path))
                if (BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant() != Sha256)
                    throw new InvalidOperationException("unsupported_engine_revision");
            this.module = module;
        }
        public void SetWork(IntPtr pointer) { work = pointer; }
        public bool Ready { get { return work != IntPtr.Zero; } }
        public int Read32(int offset)
        {
            if (!Ready || offset < 0 || offset + 4 > WorkSize) throw new InvalidOperationException("invalid_engine_work");
            return Marshal.ReadInt32(work, offset);
        }
        public int Read16(int offset)
        {
            if (!Ready || offset < 0 || offset + 2 > WorkSize) throw new InvalidOperationException("invalid_engine_work");
            return (ushort)Marshal.ReadInt16(work, offset);
        }
        public int Actor(int effectId) { return Read32(effectId == 4 ? 0x3d00 : 0x3c98); }
        public int ListType { get { return Read16(0x3dd2); } }
        public bool AllowsLocation(int player, int position)
        {
            if (!Ready || player < 0 || player > 1 || position < 0 || position > 12)
                throw new InvalidOperationException("invalid_location_query");
            // The Location menu's native predicate is called with these arguments in C2DCE0.
            IntPtr pointer = Marshal.ReadIntPtr(work, 0x3d18);
            long rva = pointer.ToInt64() - module.ToInt64();
            if (rva < 0 || rva >= 0x1290000) throw new InvalidOperationException("unverified_location_predicate");
            return ((LocationPredicate)Marshal.GetDelegateForFunctionPointer(pointer, typeof(LocationPredicate)))(player, position, 0) != 0;
        }
        public string Marker(int effectId)
        {
            return effectId == 4 ? Read32(0x3cd0) + ":" + Read32(0x3cec) + ":" + Read32(0x3cd4) + ":" + Actor(effectId) :
                Read32(0x3c94) + ":" + Actor(effectId);
        }
        public bool Pending(int effectId) { return Read32(effectId == 4 ? 0x3cd0 : 0x3c94) != 0; }
    }
}
