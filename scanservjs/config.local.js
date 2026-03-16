/* eslint-disable no-unused-vars */
const options = { paths: ['/usr/lib/scanservjs'] };
const fs = require('fs/promises');
const path = require('path');
const Process = require(require.resolve('./server/classes/process', options));

function quoteShell(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function sorterCommand(subcommand, filePath) {
  if (!filePath) {
    return `python3 /opt/scanservjs-sorter/sorter_engine.py ${subcommand}`;
  }
  return `python3 /opt/scanservjs-sorter/sorter_engine.py ${subcommand} --review-file ${quoteShell(filePath)}`;
}

function sorterEnabled() {
  return String(process.env.SORTER_ENABLE || '').toLowerCase() === 'true';
}

async function copyFileSafe(src, destDir) {
  await fs.mkdir(destDir, { recursive: true });
  const destinationPath = path.join(destDir, path.basename(src));
  await fs.copyFile(src, destinationPath);
  return destinationPath;
}

module.exports = {
  /**
   * @param {Configuration} config
   */
  afterConfig(config) {},

  /**
   * @param {ScanDevice[]} devices
   */
  afterDevices(devices) {},

  /**
   * @param {FileInfo} fileInfo
   * @returns {Promise.<any>}
   */
  async afterScan(fileInfo) {
    const sorterEnabled = String(process.env.SORTER_ENABLE || '').toLowerCase() === 'true';
    const sorterInbox = process.env.SORTER_INBOX_DIR;

    if (sorterEnabled && sorterInbox) {
      try {
        const destinationPath = await copyFileSafe(fileInfo.fullname, sorterInbox);
        return `Sorter inbox copy: ${destinationPath}`;
      } catch (error) {
        return error;
      }
    }

    const destinationDir = process.env.COPY_SCANS_TO;
    if (!destinationDir) {
      return;
    }

    try {
      const destinationPath = await copyFileSafe(fileInfo.fullname, destinationDir);
      return `Copied to ${destinationPath}`;
    } catch (error) {
      return error;
    }
  },

  /**
   * @type {Action[]}
   */
  actions: [
    {
      name: 'Sortieren + sichere hochladen',
      async execute(fileInfo) {
        if (!sorterEnabled()) {
          return 'Sortierer ist deaktiviert (sorter_enable=false).';
        }
        return await Process.spawn(`bash -lc ${quoteShell(sorterCommand('run'))}`);
      }
    },
    {
      name: 'Review freigeben und hochladen',
      async execute(fileInfo) {
        if (!sorterEnabled()) {
          return 'Sortierer ist deaktiviert (sorter_enable=false).';
        }
        if (!path.basename(fileInfo.fullname).startsWith('REVIEW_')) {
          return 'Nur REVIEW_ Dateien koennen freigegeben werden.';
        }
        return await Process.spawn(`bash -lc ${quoteShell(sorterCommand('approve', fileInfo.fullname))}`);
      }
    },
    {
      name: 'Review verwerfen',
      async execute(fileInfo) {
        if (!sorterEnabled()) {
          return 'Sortierer ist deaktiviert (sorter_enable=false).';
        }
        if (!path.basename(fileInfo.fullname).startsWith('REVIEW_')) {
          return 'Nur REVIEW_ Dateien koennen verworfen werden.';
        }
        return await Process.spawn(`bash -lc ${quoteShell(sorterCommand('reject', fileInfo.fullname))}`);
      }
    }
  ]
};
