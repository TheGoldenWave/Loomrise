export function createLocalFileReader(context) {
  let generation = 0;
  return {
    invalidate() { generation += 1; },
    async read(file) {
      const key = context();
      const current = ++generation;
      const valid = () => key !== null && current === generation && context() === key;
      if (!key) return { status: 'stale' };
      if (file.size > 512000) return { status: 'error', key, message: '前端演示只接受 500 KB 以内文件。没有读取文件，请使用较小文本。' };
      const textual = /\.(txt|md|csv|json)$/i.test(file.name);
      try {
        const body = textual ? await file.text() : '';
        if (!valid()) return { status: 'stale' };
        if (body.length > 50000) return { status: 'error', key, message: '文本超过本地演示 50000 字限制，请拆分资料；没有截断或登记。' };
        return { status: 'ready', key, body, meta: { name: file.name, size: file.size, metadataOnly: !textual } };
      } catch {
        return valid() ? { status: 'error', key, message: '文件读取失败，草稿仍保留。请重新选择文件或粘贴有权使用的文本。' } : { status: 'stale' };
      }
    },
  };
}
