//! Filesystem-aware staging. Always produce an independent file; a hard link
//! would let a failed save damage the last good archive.
use std::fs::{self, File};
use std::io;
use std::path::Path;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArchiveCopyMethod {
    Clone,
    Copy,
}

/// Copy an archive to a new path in a private staging directory. Prefer
/// copy-on-write, but retain atomic publication on filesystems without it.
/// The destination must not exist, and its parent must be owned by the caller.
pub fn stage_archive_copy(source: &Path, destination: &Path) -> io::Result<ArchiveCopyMethod> {
    stage_archive_copy_with(source, destination, clone_file)
}

fn stage_archive_copy_with(
    source: &Path,
    destination: &Path,
    clone: impl FnOnce(&File, &Path, &Path) -> io::Result<()>,
) -> io::Result<ArchiveCopyMethod> {
    match fs::symlink_metadata(destination) {
        Ok(_) => {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "Staging destination already exists",
            ))
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }
    let input = File::open(source)?;
    if !input.metadata()?.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Archive must be a regular file",
        ));
    }
    if clone(&input, source, destination).is_ok() {
        return Ok(ArchiveCopyMethod::Clone);
    }
    // A failed clone can have created a partially populated staging file. Only
    // remove that caller-owned destination before the ordinary-copy fallback.
    match fs::remove_file(destination) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }
    fs::copy(source, destination)?;
    Ok(ArchiveCopyMethod::Copy)
}

#[cfg(target_os = "macos")]
fn clone_file(input: &File, _source: &Path, destination: &Path) -> io::Result<()> {
    rustix::fs::fclonefileat(
        input,
        rustix::fs::CWD,
        destination,
        rustix::fs::CloneFlags::empty(),
    )
    .map_err(Into::into)
}

#[cfg(target_os = "linux")]
fn clone_file(input: &File, _source: &Path, destination: &Path) -> io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(destination)?;
    rustix::fs::ioctl_ficlone(&output, input).map_err(Into::into)
}

#[cfg(windows)]
fn clone_file(input: &File, source: &Path, destination: &Path) -> io::Result<()> {
    use std::io::{Read, Seek, SeekFrom, Write};
    use std::os::windows::{ffi::OsStrExt, io::AsRawHandle};
    use windows_sys::Win32::{
        Storage::FileSystem::{GetDiskFreeSpaceW, GetVolumePathNameW},
        System::{
            Ioctl::{DUPLICATE_EXTENTS_DATA, FSCTL_DUPLICATE_EXTENTS_TO_FILE},
            IO::DeviceIoControl,
        },
    };

    let source_path: Vec<u16> = fs::canonicalize(source)?
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    let mut volume = vec![0u16; 32768];
    let (mut sectors, mut bytes, mut free, mut total) = (0, 0, 0, 0);
    // SAFETY: All strings are terminated and all output pointers reference
    // live buffers with the sizes passed to these synchronous Win32 calls.
    unsafe {
        if GetVolumePathNameW(
            source_path.as_ptr(),
            volume.as_mut_ptr(),
            volume.len() as u32,
        ) == 0
            || GetDiskFreeSpaceW(
                volume.as_ptr(),
                &mut sectors,
                &mut bytes,
                &mut free,
                &mut total,
            ) == 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    let cluster = u64::from(sectors) * u64::from(bytes);
    if cluster == 0 || cluster > 1024 * 1024 {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "Unsupported cluster size",
        ));
    }
    let length = input.metadata()?.len();
    if length > i64::MAX as u64 {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "File exceeds clone offset range",
        ));
    }
    let aligned = length / cluster * cluster;
    if aligned == 0 {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "File smaller than one cluster",
        ));
    }
    let mut output = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(destination)?;
    output.set_len(length)?;
    let mut offset = 0;
    // ReFS requires cluster-aligned ranges smaller than 4 GiB. Clone complete
    // clusters in 1 GiB chunks and copy only the final partial cluster.
    let chunk_limit = (1024 * 1024 * 1024 / cluster) * cluster;
    while offset < aligned {
        let count = (aligned - offset).min(chunk_limit);
        let request = DUPLICATE_EXTENTS_DATA {
            FileHandle: input.as_raw_handle(),
            SourceFileOffset: offset as i64,
            TargetFileOffset: offset as i64,
            ByteCount: count as i64,
        };
        let mut returned = 0;
        // SAFETY: Both file handles and the input structure outlive this
        // synchronous call. No asynchronous or output buffer is supplied.
        if unsafe {
            DeviceIoControl(
                output.as_raw_handle(),
                FSCTL_DUPLICATE_EXTENTS_TO_FILE,
                (&request as *const DUPLICATE_EXTENTS_DATA).cast(),
                std::mem::size_of_val(&request) as u32,
                std::ptr::null_mut(),
                0,
                &mut returned,
                std::ptr::null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        offset += count;
    }
    let mut tail_source = input.try_clone()?;
    tail_source.seek(SeekFrom::Start(aligned))?;
    output.seek(SeekFrom::Start(aligned))?;
    let mut tail = vec![0; (length - aligned) as usize];
    tail_source.read_exact(&mut tail)?;
    output.write_all(&tail)?;
    Ok(())
}

#[cfg(not(any(target_os = "macos", target_os = "linux", windows)))]
fn clone_file(_input: &File, _source: &Path, _destination: &Path) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "File cloning is unavailable",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Seek, SeekFrom, Write};

    #[test]
    fn failed_clone_discards_partial_stage_before_copying() {
        let root = tempfile::tempdir().unwrap();
        let source = root.path().join("source");
        let stage = root.path().join("stage");
        fs::write(&source, b"complete archive").unwrap();
        let method = stage_archive_copy_with(&source, &stage, |_, _, destination| {
            fs::write(destination, b"incomplete clone with an extra-long tail")?;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "clone unavailable",
            ))
        })
        .unwrap();
        assert_eq!(method, ArchiveCopyMethod::Copy);
        assert_eq!(fs::read(&stage).unwrap(), b"complete archive");
        assert_eq!(fs::read(&source).unwrap(), b"complete archive");
    }

    #[test]
    fn staged_copy_preserves_partial_tail_and_isolates_writes() {
        let root = tempfile::tempdir().unwrap();
        let source = root.path().join("source");
        let destination = root.path().join("stage");
        let bytes: Vec<u8> = (0..1024 * 1024 + 137)
            .map(|index| (index % 251) as u8)
            .collect();
        fs::write(&source, &bytes).unwrap();
        let method = stage_archive_copy(&source, &destination).unwrap();
        eprintln!("Archive staging method: {method:?}");
        assert_eq!(fs::read(&destination).unwrap(), bytes);
        let mut output = fs::OpenOptions::new()
            .write(true)
            .open(&destination)
            .unwrap();
        output.seek(SeekFrom::Start(65530)).unwrap();
        output.write_all(b"changed block boundary").unwrap();
        output.set_len(65580).unwrap();
        assert_eq!(fs::read(&source).unwrap(), bytes);
        assert_eq!(
            stage_archive_copy(&source, &destination)
                .unwrap_err()
                .kind(),
            io::ErrorKind::AlreadyExists
        );
    }
}
