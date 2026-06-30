/**
 * Scheduler Store
 * 管理定时任务
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { SchedulerJobView } from '@/types/protocol'

export const useSchedulerStore = defineStore('scheduler', () => {
  const jobs = ref<SchedulerJobView[]>([])
  const selectedJobId = ref<string | null>(null)
  const runs = ref<any[]>([])

  function setJobs(newJobs: SchedulerJobView[]): void {
    jobs.value = newJobs
  }

  function selectJob(jobId: string | null): void {
    selectedJobId.value = jobId
    runs.value = []
  }

  function setRuns(newRuns: any[]): void {
    runs.value = newRuns
  }

  function addJob(job: SchedulerJobView): void {
    const existingIndex = jobs.value.findIndex((j) => j.payload?.job_id === job.payload?.job_id)
    if (existingIndex !== -1) {
      jobs.value[existingIndex] = job
    } else {
      jobs.value.unshift(job)
    }
  }

  function removeJob(jobId: string): void {
    const index = jobs.value.findIndex((j) => j.payload?.job_id === jobId)
    if (index !== -1) {
      jobs.value.splice(index, 1)
    }
    if (selectedJobId.value === jobId) {
      selectedJobId.value = null
    }
  }

  function updateJob(jobId: string, updates: Partial<SchedulerJobView>): void {
    const index = jobs.value.findIndex((j) => j.payload?.job_id === jobId)
    if (index !== -1) {
      jobs.value[index] = { ...jobs.value[index], ...updates }
    }
  }

  return {
    jobs,
    selectedJobId,
    runs,
    setJobs,
    selectJob,
    setRuns,
    addJob,
    removeJob,
    updateJob,
  }
})
