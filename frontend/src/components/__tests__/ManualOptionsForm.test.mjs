import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'

import ManualOptionsForm from '../ManualOptionsForm.vue'

describe('ManualOptionsForm', () => {
  it('keeps form values while switching modes and emits the manual config', async () => {
    const wrapper = mount(ManualOptionsForm, {
      props: { mode: 'manual' },
      global: { plugins: [ElementPlus] },
    })

    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.setProps({ mode: 'project' })
    await wrapper.setProps({ mode: 'manual' })

    const updates = wrapper.emitted('update:config')
    expect(updates.at(-1)[0].crc.byte_swap).toBe(true)
    wrapper.unmount()
  })
})
