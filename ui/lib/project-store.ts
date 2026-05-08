import { create } from "zustand";

type ProjectStore = {
  project: string;
  setProject: (project: string) => void;
};

export const useProjectStore = create<ProjectStore>((set) => ({
  project: "",  // empty = all memories (user-scoped, not project-scoped)
  setProject: (project) => set({ project }),
}));
