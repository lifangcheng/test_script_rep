import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface TaskStatus {
  task_id: string;
  status: string;
  error?: any;
  logs?: any[];
  output_dir?: string;
  created_at?: number;
  updated_at?: number;
}

export interface AppState {
  // 当前任务状态
  currentTask: TaskStatus | null;
  
  // 任务历史记录
  taskHistory: TaskStatus[];
  
  // UI状态
  isLoading: boolean;
  lastError: string | null;
  
  // 操作
  setCurrentTask: (task: TaskStatus | null) => void;
  updateTaskStatus: (taskId: string, status: Partial<TaskStatus>) => void;
  addToHistory: (task: TaskStatus) => void;
  clearHistory: () => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearError: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      // 初始状态
      currentTask: null,
      taskHistory: [],
      isLoading: false,
      lastError: null,
      
      // 操作实现
      setCurrentTask: (task) => set({ currentTask: task }),
      
      updateTaskStatus: (taskId, statusUpdate) => {
        const state = get();
        
        // 更新当前任务
        if (state.currentTask?.task_id === taskId) {
          set({
            currentTask: {
              ...state.currentTask,
              ...statusUpdate,
              updated_at: Date.now(),
            }
          });
        }
        
        // 更新历史记录
        const updatedHistory = state.taskHistory.map(task => 
          task.task_id === taskId 
            ? { ...task, ...statusUpdate, updated_at: Date.now() }
            : task
        );
        
        set({ taskHistory: updatedHistory });
      },
      
      addToHistory: (task) => {
        const state = get();
        const existingIndex = state.taskHistory.findIndex(t => t.task_id === task.task_id);
        
        if (existingIndex >= 0) {
          // 更新现有记录
          const updatedHistory = [...state.taskHistory];
          updatedHistory[existingIndex] = { ...task, updated_at: Date.now() };
          set({ taskHistory: updatedHistory });
        } else {
          // 添加新记录
          set({
            taskHistory: [
              { ...task, created_at: Date.now(), updated_at: Date.now() },
              ...state.taskHistory.slice(0, 9) // 保留最近10个任务
            ]
          });
        }
      },
      
      clearHistory: () => set({ taskHistory: [] }),
      
      setLoading: (loading) => set({ isLoading: loading }),
      
      setError: (error) => set({ lastError: error }),
      
      clearError: () => set({ lastError: null }),
    }),
    {
      name: 'can-agent-storage',
      partialize: (state) => ({
        currentTask: state.currentTask,
        taskHistory: state.taskHistory,
      }),
    }
  )
);