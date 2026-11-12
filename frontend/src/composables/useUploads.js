// 上传控件状态:trace / DBC / DataID 的文件列表与 Element Plus 回调。
// 文件大小上限来自 /api/limits;加载完成前不做客户端拦截(服务端仍会兜底)。

import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

export function useUploads({ limits }) {
  const fileList = ref([])
  const selectedFile = ref(null)
  const dbcList = ref([])
  const dbcFiles = ref([])
  const dataidList = ref([])
  const dataidFile = ref(null)

  const uploadLimitBytes = computed(() =>
    limits.maxUploadMb ? limits.maxUploadMb * 1024 * 1024 : Infinity,
  )

  function onFileChange(uploadFile) {
    if (
      uploadFile.raw &&
      Number.isFinite(uploadLimitBytes.value) &&
      uploadFile.raw.size > uploadLimitBytes.value
    ) {
      ElMessage.error(
        `trace 文件超过 ${limits.maxUploadMb}MB 上限，请截取日志后重试。`,
      )
      selectedFile.value = null
      fileList.value = []
      return
    }
    selectedFile.value = uploadFile.raw || null
    fileList.value = uploadFile.raw ? [uploadFile] : []
  }

  function onFileRemove() {
    selectedFile.value = null
    fileList.value = []
  }

  function onFileExceed() {
    ElMessage.warning('一次只能上传一个 trace 文件，请先移除已选文件。')
  }

  function onDbcChange(_uploadFile, uploadFiles) {
    dbcList.value = [...uploadFiles]
    dbcFiles.value = uploadFiles.map((item) => item.raw).filter(Boolean)
  }

  function onDbcRemove(_uploadFile, uploadFiles) {
    dbcList.value = [...uploadFiles]
    dbcFiles.value = uploadFiles.map((item) => item.raw).filter(Boolean)
  }

  function onDbcExceed() {
    ElMessage.warning(`最多一次上传 ${limits.maxDbcFiles ?? '…'} 个 DBC 文件。`)
  }

  function onDataidChange(uploadFile) {
    dataidFile.value = uploadFile.raw || null
    dataidList.value = uploadFile.raw ? [uploadFile] : []
  }

  function onDataidRemove() {
    dataidFile.value = null
    dataidList.value = []
  }

  function onDataidExceed() {
    ElMessage.warning('一次只能上传一个 DataID 文件，请先移除已选文件。')
  }

  return {
    fileList,
    selectedFile,
    dbcList,
    dbcFiles,
    dataidList,
    dataidFile,
    uploadLimitBytes,
    onFileChange,
    onFileRemove,
    onFileExceed,
    onDbcChange,
    onDbcRemove,
    onDbcExceed,
    onDataidChange,
    onDataidRemove,
    onDataidExceed,
  }
}
