using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
using System.Windows.Forms;
using ComDataObject = System.Runtime.InteropServices.ComTypes.IDataObject;
using IDataObject = System.Windows.Forms.IDataObject;

namespace WizardBar
{
    /// <summary>Files dragged onto the button. From Explorer they have a place on disk, and Wizard reads them there (as From
    /// this PC does: protected files open only from their original place). An Outlook attachment or message has no place
    /// on disk, so it is saved first, under the home folder's dropped\ (kept for a day).</summary>
    internal static class Dropped
    {
        public const int Limit = 5;
        private const string Descriptor = "FileGroupDescriptorW";
        private const string Contents = "FileContents";

        public static bool HasFiles(IDataObject data) =>
            data != null && (data.GetDataPresent(DataFormats.FileDrop) || data.GetDataPresent(Descriptor));

        /// <summary>The dropped files' paths (folders too: the service says it cannot read those). Call it during the
        /// drop: Outlook's data is gone afterwards.</summary>
        public static List<string> Paths(IDataObject data, string folder)
        {
            if (data.GetData(DataFormats.FileDrop) is string[] files) return files.Take(Limit).ToList();
            return data.GetDataPresent(Descriptor) ? SaveVirtual(data, folder) : new List<string>();
        }

        /// <summary>Removes what earlier drops saved, a day later.</summary>
        public static void Tidy(string folder)
        {
            try
            {
                if (!Directory.Exists(folder)) return;
                foreach (var old in new DirectoryInfo(folder).GetDirectories().Where(d => d.CreationTimeUtc < DateTime.UtcNow.AddDays(-1)))
                    old.Delete(true);
            }
            catch (Exception error) { Log.Error("tidy dropped files", error); }
        }

        private static List<string> SaveVirtual(IDataObject data, string folder)
        {
            var saved = new List<string>();
            var names = DescriptorNames(data.GetData(Descriptor) as MemoryStream);
            if (!(data is ComDataObject com) || names.Count == 0) return saved;
            Tidy(folder);
            var target = Path.Combine(folder, DateTime.Now.ToString("yyyyMMdd-HHmmss-fff"));
            Directory.CreateDirectory(target);
            for (var i = 0; i < names.Count && saved.Count < Limit; i++)
            {
                try
                {
                    var bytes = ReadContents(com, i);
                    if (bytes == null) continue;
                    var path = Unique(Path.Combine(target, SafeName(names[i])));
                    File.WriteAllBytes(path, bytes);
                    saved.Add(path);
                }
                catch (Exception error) { Log.Error("save dropped file " + names[i], error); }
            }
            return saved;
        }

        /// <summary>FILEGROUPDESCRIPTORW: a count, then 592-byte FILEDESCRIPTORW records with the name at byte 72.</summary>
        private static List<string> DescriptorNames(MemoryStream stream)
        {
            var names = new List<string>();
            if (stream == null) return names;
            var bytes = stream.ToArray();
            if (bytes.Length < 4) return names;
            var count = BitConverter.ToInt32(bytes, 0);
            for (var i = 0; i < count; i++)
            {
                var offset = 4 + i * 592 + 72;
                if (offset + 520 > bytes.Length) break;
                var name = Encoding.Unicode.GetString(bytes, offset, 520);
                var end = name.IndexOf('\0');
                names.Add(end >= 0 ? name.Substring(0, end) : name);
            }
            return names;
        }

        private static string SafeName(string name)
        {
            var clean = new string(Path.GetFileName(name.Replace('/', '\\')).Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c).ToArray()).Trim();
            if (clean.Length > 120) clean = clean.Substring(0, 100) + Path.GetExtension(clean);
            return clean.Length > 0 ? clean : "dropped file";
        }

        private static string Unique(string path)
        {
            var stem = Path.Combine(Path.GetDirectoryName(path) ?? "", Path.GetFileNameWithoutExtension(path));
            var extension = Path.GetExtension(path);
            for (var n = 2; File.Exists(path); n++) path = stem + " (" + n + ")" + extension;
            return path;
        }

        /// <summary>The bytes of the index-th dropped file: a stream (an attachment), memory, or a structured storage (a whole
        /// Outlook message, saved as a .msg file).</summary>
        private static byte[] ReadContents(ComDataObject com, int index)
        {
            var format = new FORMATETC
            {
                cfFormat = unchecked((short)DataFormats.GetFormat(Contents).Id),
                dwAspect = DVASPECT.DVASPECT_CONTENT,
                lindex = index,
                ptd = IntPtr.Zero,
                tymed = TYMED.TYMED_ISTREAM | TYMED.TYMED_HGLOBAL | TYMED.TYMED_ISTORAGE,
            };
            com.GetData(ref format, out var medium);
            try
            {
                switch (medium.tymed)
                {
                    case TYMED.TYMED_ISTREAM:
                        return ReadStream((IStream)Marshal.GetObjectForIUnknown(medium.unionmember));
                    case TYMED.TYMED_HGLOBAL:
                        return ReadGlobal(medium.unionmember, -1);
                    case TYMED.TYMED_ISTORAGE:
                        return ReadStorage((IStorage)Marshal.GetObjectForIUnknown(medium.unionmember));
                    default:
                        return null;
                }
            }
            finally { ReleaseStgMedium(ref medium); }
        }

        private static byte[] ReadStream(IStream stream)
        {
            try { stream.Seek(0, 0, IntPtr.Zero); } catch (COMException) { }
            stream.Stat(out var stat, 1);
            var output = new MemoryStream();
            var buffer = new byte[64 * 1024];
            var read = Marshal.AllocCoTaskMem(sizeof(int));
            try
            {
                while (true)
                {
                    stream.Read(buffer, buffer.Length, read);
                    var count = Marshal.ReadInt32(read);
                    if (count <= 0) break;
                    output.Write(buffer, 0, count);
                    if (stat.cbSize > 0 && output.Length >= stat.cbSize) break;
                }
            }
            finally { Marshal.FreeCoTaskMem(read); }
            return output.ToArray();
        }

        private static byte[] ReadGlobal(IntPtr global, long length)
        {
            var size = (long)GlobalSize(global).ToUInt64();
            if (length >= 0) size = Math.Min(size, length);
            var pointer = GlobalLock(global);
            try
            {
                var bytes = new byte[size];
                Marshal.Copy(pointer, bytes, 0, (int)size);
                return bytes;
            }
            finally { GlobalUnlock(global); }
        }

        private static byte[] ReadStorage(IStorage source)
        {
            Check(CreateILockBytesOnHGlobal(IntPtr.Zero, true, out var lockBytes));
            try
            {
                Check(StgCreateDocfileOnILockBytes(lockBytes, StgmCreate | StgmReadWrite | StgmShareExclusive, 0, out var copy));
                try
                {
                    source.CopyTo(0, IntPtr.Zero, IntPtr.Zero, copy);
                    copy.Commit(0);
                    lockBytes.Stat(out var stat, 1);
                    Check(GetHGlobalFromILockBytes(lockBytes, out var global));
                    return ReadGlobal(global, stat.cbSize);
                }
                finally { Marshal.ReleaseComObject(copy); }
            }
            finally { Marshal.ReleaseComObject(lockBytes); }
        }

        private static void Check(int hresult)
        {
            if (hresult < 0) Marshal.ThrowExceptionForHR(hresult);
        }

        private const uint StgmCreate = 0x1000, StgmReadWrite = 0x2, StgmShareExclusive = 0x10;

        // Only the methods called here are declared with their real signatures; the others keep their place in the table.
        [ComImport, Guid("0000000B-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IStorage
        {
            void CreateStream();
            void OpenStream();
            void CreateStorage();
            void OpenStorage();
            void CopyTo(int ciidExclude, IntPtr rgiidExclude, IntPtr snbExclude, IStorage destination);
            void MoveElementTo();
            void Commit(int flags);
        }

        [ComImport, Guid("0000000A-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface ILockBytes
        {
            void ReadAt();
            void WriteAt();
            void Flush();
            void SetSize();
            void LockRegion();
            void UnlockRegion();
            void Stat(out System.Runtime.InteropServices.ComTypes.STATSTG stat, int flags);
        }

        [DllImport("ole32.dll")] private static extern int CreateILockBytesOnHGlobal(IntPtr global, bool deleteOnRelease, out ILockBytes lockBytes);
        [DllImport("ole32.dll")] private static extern int StgCreateDocfileOnILockBytes(ILockBytes lockBytes, uint mode, uint reserved, out IStorage storage);
        [DllImport("ole32.dll")] private static extern int GetHGlobalFromILockBytes(ILockBytes lockBytes, out IntPtr global);
        [DllImport("ole32.dll")] private static extern void ReleaseStgMedium(ref STGMEDIUM medium);
        [DllImport("kernel32.dll")] private static extern IntPtr GlobalLock(IntPtr global);
        [DllImport("kernel32.dll")] private static extern bool GlobalUnlock(IntPtr global);
        [DllImport("kernel32.dll")] private static extern UIntPtr GlobalSize(IntPtr global);
    }
}
