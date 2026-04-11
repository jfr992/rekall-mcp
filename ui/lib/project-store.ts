import { create } from "zustand";

type ProjectStore = {
  project: string;
  setProject: (project: string) => void;
};

export const useProjectStore = create<ProjectStore>((set) => ({
  project: "general",
  setProject: (project) => set({ project }),
}));
