<template>
  <el-card class="block" shadow="never" :aria-busy="projectLoading">
    <template #header>
      <div class="card-head">
        <span class="step">1</span>
        <span>选择项目</span>
        <span class="muted"
          >项目配置来自服务端扫描的 projects/ 目录，与 CLI
          共用同一校验口径</span
        >
      </div>
    </template>

    <el-select
      :model-value="projectId"
      filterable
      clearable
      :disabled="projectLoading || running"
      :loading="projectLoading"
      placeholder="按分组 / 项目选择"
      class="project-select"
      @update:model-value="$emit('update:projectId', $event)"
    >
      <el-option-group
        v-for="group in projectGroups"
        :key="group.label"
        :label="group.label"
      >
        <el-option
          v-for="projectItem in group.items"
          :key="projectItem.id"
          :label="projectLabel(projectItem)"
          :value="projectItem.id"
        />
      </el-option-group>
    </el-select>
    <div
      v-if="projectLoading"
      class="empty-projects"
      role="status"
      aria-live="polite"
    >
      <span class="muted">正在加载项目列表…</span>
    </div>
    <div v-else-if="!projects.length && !loadError" class="empty-projects">
      <span class="muted"
        >服务端没有扫描到项目。可以直接上传 DBC 和 trace 手动校验。</span
      >
      <el-button size="small" type="primary" plain @click="$emit('manual')">
        切到手动上传
      </el-button>
    </div>

    <div v-if="project" class="project-detail">
      <div class="detail-row">
        <span v-for="item in highlights" :key="item.label" class="detail-item">
          <span class="muted">{{ item.label }}</span>
          <span class="mono">{{ item.value }}</span>
        </span>
      </div>
      <div class="detail-row muted">
        DBC：{{ project.dbc_files.join('、') || '无' }}
      </div>
      <div v-if="project.sample_traces.length" class="detail-row">
        <span class="muted">仓库内示例 trace：</span>
        <el-button
          v-for="traceName in project.sample_traces"
          :key="traceName"
          size="small"
          link
          type="primary"
          :disabled="running"
          @click="$emit('sample', traceName)"
        >
          {{ traceName }}
        </el-button>
        <span class="muted">点击直接校验，无需上传</span>
      </div>
    </div>
  </el-card>
</template>

<script setup>
defineProps({
  projectId: { type: String, default: '' },
  projects: { type: Array, default: () => [] },
  projectGroups: { type: Array, default: () => [] },
  project: { type: Object, default: null },
  projectLoading: { type: Boolean, default: false },
  highlights: { type: Array, default: () => [] },
  loadError: { type: String, default: '' },
  running: { type: Boolean, default: false },
})

defineEmits(['update:projectId', 'manual', 'sample'])

function projectLabel(item) {
  return `${item.oem.toUpperCase()} / ${item.model}`
}
</script>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.card-head .muted {
  margin-left: auto;
}
.step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 12px;
  background: var(--el-color-primary);
  color: #fff;
}
.project-select {
  width: 420px;
  max-width: 100%;
  margin-top: 8px;
}
.empty-projects {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.project-detail {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.detail-row {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  font-size: 12px;
  align-items: baseline;
  overflow-wrap: anywhere;
}
.detail-item {
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
}
@media (max-width: 720px) {
  .card-head {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .card-head .muted {
    width: 100%;
    margin-left: 30px;
  }
  .project-select {
    width: 100%;
  }
  .empty-projects {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
