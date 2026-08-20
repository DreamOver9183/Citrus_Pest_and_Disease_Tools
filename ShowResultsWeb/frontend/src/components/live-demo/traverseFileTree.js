// 遞迴解析拖放的資料夾目錄結構
export const traverseFileTree = (entry) => {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => {
        resolve([file]);
      }, () => resolve([]));
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      let allEntries = [];

      const readEntries = () => {
        dirReader.readEntries((entries) => {
          if (entries.length === 0) {
            Promise.all(allEntries.map(traverseFileTree)).then((files) => {
              resolve(files.flat());
            });
          } else {
            allEntries.push(...entries);
            readEntries();
          }
        }, () => resolve([]));
      };
      readEntries();
    } else {
      resolve([]);
    }
  });
};
