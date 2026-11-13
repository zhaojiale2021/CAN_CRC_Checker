// 项目目录:加载、按 OEM 分组、当前项目与摘要。纯展示状态,校验仍走服务端 id。

import { computed, ref } from 'vue'

import { fetchProjects } from '../api.js'
import { findProject, groupByOem, summaryHighlights } from '../projects.js'

export function useProjects({ isRunning } = {}) {
  const projects = ref([])
  const projectId = ref('')
  const projectLoading = ref(false)
  const loadError = ref('')

  const projectGroups = computed(() => groupByOem(projects.value))
  const project = computed(() => findProject(projects.value, projectId.value))
  const highlights = computed(() => summaryHighlights(project.value))
  const configMaxFrames = computed(
    () => project.value?.summary?.default_max_frames ?? null,
  )

  async function loadProjects() {
    if (projectLoading.value || isRunning?.()) return
    projectLoading.value = true
    try {
      const data = await fetchProjects()
      projects.value = data.projects || []
      // A single project is the common local case; preselect it so the page is
      // one upload away from a result instead of asking for a pointless choice.
      if (!projects.value.some((item) => item.id === projectId.value)) {
        projectId.value =
          projects.value.length === 1 ? projects.value[0].id : ''
      }
      loadError.value = ''
    } catch (err) {
      loadError.value = err.message
    } finally {
      projectLoading.value = false
    }
  }

  return {
    projects,
    projectId,
    projectLoading,
    loadError,
    projectGroups,
    project,
    highlights,
    configMaxFrames,
    loadProjects,
  }
}
